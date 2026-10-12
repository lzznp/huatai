package main

// kernel.go —— 画台壳与 Python 内核之间的**唯一一条通道**。
//
// 形状照 DSH 自己的做法：起一个子进程，走 stdin/stdout 传 JSON 行，诊断走 stderr。
// 为什么不用 HTTP：不占端口 ⇒ "服务没起 / 端口被占 / 僵尸服务"这一整类状态直接消失；
// 子进程随壳生死，壳一关它就跟着走。
//
// 这里只做搬运与配对（id），不含任何业务判断（业务在 server\dispatch.py）。

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Reply 是给前端看的统一回执：成功给 Result，失败给 Error/Detail。
// ★ 失败**永远**带 Error，绝不用成功回执带错误体（不许静默）。
type Reply struct {
	OK     bool            `json:"ok"`
	Status int             `json:"status"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  string          `json:"error,omitempty"`
	Detail string          `json:"detail,omitempty"`
}

// frame 是 stdio 通道上的一帧（与 server\stdio.py 的约定）。
type frame struct {
	ID     *int            `json:"id"`
	OK     bool            `json:"ok"`
	Status int             `json:"status"`
	Result json.RawMessage `json:"result"`
	Error  string          `json:"error"`
	Detail string          `json:"detail"`
}

// Kernel 管着一个 Python 子进程，并提供 Call(action, payload)。
type Kernel struct {
	mu      sync.Mutex
	cmd     *exec.Cmd
	stdin   io.WriteCloser
	pending map[int]chan frame
	nextID  int

	Root   string // 项目根（D:\画台）
	Python string // 解释器
	Script string // server\stdio.py
	PID    int
	Running bool

	lastErr    string
	stderrRing []string // 最近若干行诊断（给界面看）
}

const stderrKeep = 20

// NewKernel 自动定位项目根与解释器，但**不启动**（首次调用才起，省得空转）。
func NewKernel() *Kernel {
	k := &Kernel{pending: map[int]chan frame{}}
	k.Root, k.lastErr = findRoot()
	k.Python = findPython(k.Root)
	if k.Root != "" {
		k.Script = filepath.Join(k.Root, "server", "stdio.py")
	}
	return k
}

// findRoot：从 exe 所在目录往上找，直到找到 server\stdio.py 的那一层。
// 这样 exe 放 <根>\运行\ 或 <根>\ 都不用改配置。
func findRoot() (string, string) {
	exe, err := os.Executable()
	if err != nil {
		return "", fmt.Sprintf("拿不到 exe 路径：%v", err)
	}
	d := filepath.Dir(exe)
	for i := 0; i < 4; i++ {
		if _, err := os.Stat(filepath.Join(d, "server", "stdio.py")); err == nil {
			return d, ""
		}
		parent := filepath.Dir(d)
		if parent == d {
			break
		}
		d = parent
	}
	return "", fmt.Sprintf("从 %s 往上四层都没找到 server\\stdio.py", filepath.Dir(exe))
}

// findPython：环境变量 HUATAI_PYTHON → settings.json 的 python → 已知 conda 路径 → PATH 上的 python
func findPython(root string) string {
	if v := strings.TrimSpace(os.Getenv("HUATAI_PYTHON")); v != "" {
		return v
	}
	if root != "" {
		if b, err := os.ReadFile(filepath.Join(root, "settings.json")); err == nil {
			var s struct {
				Python string `json:"python"`
			}
			if json.Unmarshal(b, &s) == nil && strings.TrimSpace(s.Python) != "" {
				return strings.TrimSpace(s.Python)
			}
		}
	}
	known := `C:\ProgramData\miniconda3\envs\bestpic\python.exe`
	if _, err := os.Stat(known); err == nil {
		return known
	}
	return "python"
}

// Start 首次调用时把子进程拉起来。
func (k *Kernel) Start() error {
	k.mu.Lock()
	defer k.mu.Unlock()
	return k.startLocked()
}

func (k *Kernel) startLocked() error {
	if k.Running && k.cmd != nil && k.cmd.Process != nil {
		return nil
	}
	if k.Root == "" {
		return fmt.Errorf("找不到项目根：%s", k.lastErr)
	}
	if _, err := os.Stat(k.Script); err != nil {
		return fmt.Errorf("找不到 %s：%v", k.Script, err)
	}

	cmd := exec.Command(k.Python, k.Script)
	cmd.Dir = k.Root
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8")
	// Windows：别让子进程弹出一个黑窗口
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("拿不到子进程 stdin：%v", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("拿不到子进程 stdout：%v", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("拿不到子进程 stderr：%v", err)
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("起不了 %s %s：%v", k.Python, k.Script, err)
	}

	k.cmd = cmd
	k.stdin = stdin
	k.Running = true
	k.PID = cmd.Process.Pid
	k.lastErr = ""
	k.pending = map[int]chan frame{}

	go k.readLoop(stdout)
	go k.stderrLoop(stderr)
	return nil
}

func (k *Kernel) readLoop(r io.Reader) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 0, 64*1024), 8*1024*1024) // 单帧可能不小（订单全文）
	for sc.Scan() {
		line := strings.TrimSpace(strings.TrimPrefix(sc.Text(), "\ufeff"))
		if line == "" {
			continue
		}
		var f frame
		if err := json.Unmarshal([]byte(line), &f); err != nil {
			k.pushStderr("帧解析失败（stdout 上混进了非协议内容？）：" + line)
			continue
		}
		if f.ID == nil {
			k.pushStderr("收到没有 id 的帧，丢弃：" + line)
			continue
		}
		k.mu.Lock()
		ch, okc := k.pending[*f.ID]
		if okc {
			delete(k.pending, *f.ID)
		}
		k.mu.Unlock()
		if okc {
			ch <- f
		}
	}
	k.markDead("子进程 stdout 结束（EOF）：它退出了")
}

func (k *Kernel) stderrLoop(r io.Reader) {
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		k.pushStderr(sc.Text())
	}
}

func (k *Kernel) pushStderr(line string) {
	k.mu.Lock()
	defer k.mu.Unlock()
	k.stderrRing = append(k.stderrRing, line)
	if len(k.stderrRing) > stderrKeep {
		k.stderrRing = k.stderrRing[len(k.stderrRing)-stderrKeep:]
	}
}

// markDead：子进程没了，把所有等待中的请求叫醒并报错——**不许让调用方一直等**。
func (k *Kernel) markDead(why string) {
	k.mu.Lock()
	defer k.mu.Unlock()
	k.Running = false
	k.lastErr = why
	for id, ch := range k.pending {
		ch <- frame{ID: &id, OK: false, Status: 500, Error: "内核子进程已退出", Detail: why}
		delete(k.pending, id)
	}
}

// Stop 收工：先好说好散（shutdown），再兜底杀。
func (k *Kernel) Stop() {
	k.mu.Lock()
	cmd, alive := k.cmd, k.Running
	k.mu.Unlock()
	if !alive || cmd == nil || cmd.Process == nil {
		return
	}
	_ = k.Call("shutdown", nil, 3*time.Second)
	done := make(chan struct{})
	go func() { _ = cmd.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		_ = cmd.Process.Kill()
	}
	k.mu.Lock()
	k.Running = false
	k.mu.Unlock()
}

// Call 发一个动作并等回执。timeout<=0 用默认 60s。
func (k *Kernel) Call(action string, payload map[string]any, timeout time.Duration) Reply {
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	if payload == nil {
		payload = map[string]any{}
	}

	k.mu.Lock()
	if err := k.startLocked(); err != nil {
		k.mu.Unlock()
		return Reply{OK: false, Status: 500, Error: "内核没起来", Detail: err.Error()}
	}
	k.nextID++
	id := k.nextID
	ch := make(chan frame, 1)
	k.pending[id] = ch
	stdin := k.stdin
	k.mu.Unlock()

	req, _ := json.Marshal(map[string]any{"id": id, "action": action, "payload": payload})
	if _, err := stdin.Write(append(req, '\n')); err != nil {
		k.mu.Lock()
		delete(k.pending, id)
		k.mu.Unlock()
		return Reply{OK: false, Status: 500, Error: "写不进内核子进程", Detail: err.Error()}
	}

	select {
	case f := <-ch:
		if f.OK {
			return Reply{OK: true, Status: f.Status, Result: f.Result}
		}
		return Reply{OK: false, Status: f.Status, Error: f.Error, Detail: f.Detail}
	case <-time.After(timeout):
		k.mu.Lock()
		delete(k.pending, id)
		k.mu.Unlock()
		return Reply{OK: false, Status: 504, Error: "内核超时", Detail: fmt.Sprintf("%s 超过 %s 没回话", action, timeout)}
	}
}

// Status 给界面看的诊断信息（不是业务）。
type Status struct {
	Running bool     `json:"running"`
	PID     int      `json:"pid"`
	Root    string   `json:"root"`
	Python  string   `json:"python"`
	Script  string   `json:"script"`
	LastErr string   `json:"lastErr"`
	Stderr  []string `json:"stderr"`
}

func (k *Kernel) Status() Status {
	k.mu.Lock()
	defer k.mu.Unlock()
	s := Status{
		Running: k.Running, PID: k.PID, Root: k.Root, Python: k.Python,
		Script: k.Script, LastErr: k.lastErr,
		Stderr: append([]string{}, k.stderrRing...),
	}
	return s
}
