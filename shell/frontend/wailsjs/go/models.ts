export namespace main {
	
	export class Reply {
	    ok: boolean;
	    status: number;
	    result?: number[];
	    error?: string;
	    detail?: string;
	
	    static createFrom(source: any = {}) {
	        return new Reply(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ok = source["ok"];
	        this.status = source["status"];
	        this.result = source["result"];
	        this.error = source["error"];
	        this.detail = source["detail"];
	    }
	}
	export class Status {
	    running: boolean;
	    pid: number;
	    root: string;
	    python: string;
	    script: string;
	    lastErr: string;
	    stderr: string[];
	
	    static createFrom(source: any = {}) {
	        return new Status(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.running = source["running"];
	        this.pid = source["pid"];
	        this.root = source["root"];
	        this.python = source["python"];
	        this.script = source["script"];
	        this.lastErr = source["lastErr"];
	        this.stderr = source["stderr"];
	    }
	}

}

