"""Controller-owned Windows job, attached before its child is allowed to boot."""
import ctypes
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4
from agent_runtime.common import append, canonical, now, redact, require


class Job:
    def __init__(self, pid):
        require(os.name == "nt", "platform", "Task09 release contract currently requires Windows x64")
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong), ("flags", w.DWORD),
                        ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t), ("active_processes", w.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Limits(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.k.CreateJobObjectW.restype = ctypes.c_void_p
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = ctypes.c_void_p
        self.k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.k.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.k.TerminateJobObject.argtypes = [ctypes.c_void_p, w.UINT]
        self.k.CloseHandle.argtypes = [ctypes.c_void_p]
        self.name = "Task09-"+uuid4().hex
        self.handle = self.k.CreateJobObjectW(None, self.name)
        require(self.handle, "job", "cannot create owned process job")
        limits = Limits(); limits.basic.flags = 0x2000
        process = self.k.OpenProcess(0x0100 | 0x0001, False, pid)
        try:
            require(process and self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                    and self.k.AssignProcessToJobObject(self.handle, process), "job", "cannot attach owned process")
        except BaseException:
            self.k.CloseHandle(self.handle); self.handle = None
            raise
        finally:
            if process: self.k.CloseHandle(process)

    def pids(self):
        class Pids(ctypes.Structure):
            _fields_ = [("assigned", ctypes.c_ulong), ("count", ctypes.c_ulong), ("ids", ctypes.c_size_t * 256)]
        value = Pids()
        require(self.k.QueryInformationJobObject(self.handle, 3, ctypes.byref(value), ctypes.sizeof(value), None),
                "job", "cannot inspect owned process membership")
        return list(value.ids[:value.count])

    def close(self):
        if self.handle:
            self.k.TerminateJobObject(self.handle, 130)
            deadline = time.monotonic()+10
            while self.pids() and time.monotonic() < deadline:
                time.sleep(.05)
            require(not self.pids(), "cancel", "owned descendants did not exit")
            self.k.CloseHandle(self.handle); self.handle = None


def belongs_to_job(pid, name):
    """Query the exact controller-named Job at the child's actual spawn time."""
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenJobObjectW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]; kernel.OpenJobObjectW.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.BOOL)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    job = kernel.OpenJobObjectW(0x0004, False, name)
    process = kernel.OpenProcess(0x0400 | 0x1000, False, pid)
    try:
        member = w.BOOL()
        require(job and process and kernel.IsProcessInJob(process, job, ctypes.byref(member)), "job", "cannot verify exact owned Job membership")
        return bool(member.value)
    finally:
        if process: kernel.CloseHandle(process)
        if job: kernel.CloseHandle(job)



def resume_initial_thread(pid):
    """Resume a CREATE_SUSPENDED launcher only after exact Job attachment.

    This prevents the Windows venv launcher from spawning real Python before
    assignment. A suspended newly created process has one initial thread.
    """
    from ctypes import wintypes as w
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ThreadID',w.DWORD),('th32OwnerProcessID',w.DWORD),('tpBasePri',w.LONG),('tpDeltaPri',w.LONG),('dwFlags',w.DWORD)]
    k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
    k.Thread32First.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Thread32Next.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
    k.OpenThread.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenThread.restype=w.HANDLE
    k.ResumeThread.argtypes=[w.HANDLE];k.ResumeThread.restype=w.DWORD
    k.CloseHandle.argtypes=[w.HANDLE]
    snap=k.CreateToolhelp32Snapshot(0x4,0)
    require(snap and snap!=ctypes.c_void_p(-1).value,'job','cannot inspect suspended launcher thread')
    ids=[]
    try:
        entry=Entry();entry.dwSize=ctypes.sizeof(Entry);more=k.Thread32First(snap,ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID==pid:ids.append(entry.th32ThreadID)
            more=k.Thread32Next(snap,ctypes.byref(entry))
    finally:k.CloseHandle(snap)
    require(len(ids)==1,'job','expected exactly one suspended initial thread')
    h=k.OpenThread(0x0002,False,ids[0]);require(h,'job','cannot open suspended launcher thread')
    try:require(k.ResumeThread(h)==1,'job','unexpected initial suspension count')
    finally:k.CloseHandle(h)

class DriverProcess:
    def __init__(self, argv, cwd, env, directory):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.log = self.directory / "lifecycle.jsonl"
        self.stderr = (self.directory / "stderr.log").open("x", encoding="utf-8")
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1, creationflags=0x00000004)
        secrets = tuple(env.get(k, "") for k in ("DEEPSEEK_API_KEY", "TASK09_OFFLINE_CREDENTIAL"))
        def stderr_reader():
            for line in self.process.stderr:
                self.stderr.write(redact(line, secrets)); self.stderr.flush()
        self.stderr_thread = threading.Thread(target=stderr_reader, daemon=True)
        self.stderr_thread.start()
        self.messages = queue.Queue(); self.job = None
        try:
            self.job = Job(self.process.pid)
            require(belongs_to_job(self.process.pid,self.job.name),"job","launcher not attached")
            resume_initial_thread(self.process.pid)
        except BaseException:
            if self.job is not None:self.job.close();self.job=None
            self.process.kill(); self.process.wait(); self.stderr_thread.join(timeout=2); self.stderr.close(); raise
        def reader():
            try:
                for line in self.process.stdout: self.messages.put(line)
            finally: self.messages.put(None)
        self.thread = threading.Thread(target=reader, daemon=True); self.thread.start()
        append(self.log, {"event": "spawned_attached_before_boot", "pid": self.process.pid, "argv": argv, "at": now()})

    def send(self, value):
        self.process.stdin.write(canonical(value)+"\n"); self.process.stdin.flush()

    def receive(self, timeout=900):
        deadline, next_progress = time.monotonic()+timeout, time.monotonic()
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                self.close()
                raise TimeoutError("Task09 owned user-turn watchdog expired")
            if time.monotonic() >= next_progress:
                append(self.log, {"event": "membership", "pids": self.job.pids(), "at": now()})
                phase = "DSH/MCP启动或控制器等待"
                try:
                    latest = (self.directory.parent/"phase.jsonl").read_text(encoding="utf-8").splitlines()[-1]
                    phase = __import__("json").loads(latest)["phase"]
                except (OSError, ValueError, IndexError, KeyError): pass
                print("Task09："+phase+"；尚无本项结论。", flush=True)
                next_progress = time.monotonic()+30
            try: line = self.messages.get(timeout=min(1, remaining))
            except queue.Empty: continue
            require(line is not None, "driver_exit", "DSH driver closed without a completed response")
            return __import__("json").loads(line)

    def close(self):
        if self.job is not None:
            before = self.job.pids()
            self.job.close(); self.job = None
            self.process.wait(timeout=10)
            append(self.log, {"event": "terminated_owned_tree", "pids_before": before, "pids_after": [],
                              "exit_code": self.process.returncode, "at": now()})
            self.thread.join(timeout=2)
            self.stderr_thread.join(timeout=2)
            self.process.stdin.close(); self.process.stdout.close(); self.process.stderr.close(); self.stderr.close()
