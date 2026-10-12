// 完整性级别探针：打印本进程令牌的 Integrity Level（行为判据，不看 Get-Acl）
package main

import (
	"fmt"
	"os"
	"strings"
	"syscall"
	"unsafe"
)

type sidAndAttributes struct {
	Sid        *syscall.SID
	Attributes uint32
}

type tokenMandatoryLabel struct {
	Label sidAndAttributes
}

func main() {
	self, _ := os.Executable()
	fmt.Printf("exe = %s\n", self)

	var token syscall.Token
	p, err := syscall.GetCurrentProcess()
	if err != nil {
		fmt.Println("GetCurrentProcess failed:", err)
		return
	}
	if err := syscall.OpenProcessToken(p, syscall.TOKEN_QUERY, &token); err != nil {
		fmt.Println("OpenProcessToken failed:", err)
		return
	}
	defer token.Close()

	var size uint32
	_ = syscall.GetTokenInformation(token, syscall.TokenIntegrityLevel, nil, 0, &size)
	if size == 0 {
		fmt.Println("GetTokenInformation: size=0（拿不到）")
		return
	}
	buf := make([]byte, size)
	if err := syscall.GetTokenInformation(token, syscall.TokenIntegrityLevel, &buf[0], size, &size); err != nil {
		fmt.Println("GetTokenInformation failed:", err)
		return
	}
	tml := (*tokenMandatoryLabel)(unsafe.Pointer(&buf[0]))
	sidStr, _ := tml.Label.Sid.String() // 形如 S-1-16-12288；末段就是完整性 RID
	rid := ""
	if i := strings.LastIndex(sidStr, "-"); i >= 0 {
		rid = sidStr[i+1:]
	}
	name := map[string]string{"4096": "Low", "8192": "Medium", "12288": "High", "16384": "System"}[rid]
	if name == "" {
		name = "未知"
	}
	fmt.Printf("IntegrityLevel = %s (RID=%s, SID=%s)\n", name, rid, sidStr)
}
