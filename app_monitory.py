import psutil
import time
from datetime import datetime


# 读取 cgroup 限制
def get_resource_limits():
    try:
        with open('/sys/fs/cgroup/memory.max', 'r') as f:
            mem_limit = int(f.read().strip()) / (1024**3)
        with open('/sys/fs/cgroup/cpu.max', 'r') as f:
            cpu_quota, cpu_period = map(int, f.read().strip().split())
            cpu_limit = cpu_quota / cpu_period
    except (FileNotFoundError, ValueError, PermissionError):
        mem_limit = 1.0
        cpu_limit = 1.0
    return cpu_limit, mem_limit


def get_resource_usage():
    """获取当前资源使用"""
    try:
        with open('/sys/fs/cgroup/memory.current', 'r') as f:
            mem_used = int(f.read().strip()) / (1024**3)
        with open('/sys/fs/cgroup/memory.max', 'r') as f:
            mem_limit = int(f.read().strip()) / (1024**3)
    except (FileNotFoundError, ValueError, PermissionError):
        mem = psutil.virtual_memory()
        mem_used = mem.used / (1024**3)
        mem_limit = mem.total / (1024**3)

    return mem_used, mem_limit


def monitor_app():
    cpu_limit, mem_limit = get_resource_limits()

    print("=" * 80)
    print(f"Hyperliquid 数据分析应用 - 资源监控")
    print(f"容器限制: CPU={cpu_limit:.1f}核, 内存={mem_limit:.2f}GB")
    print("=" * 80)

    while True:
        mem_used, mem_limit = get_resource_usage()
        mem_percent = (mem_used / mem_limit) * 100

        cpu_percent = psutil.cpu_percent(interval=1)

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
        print(
            f"内存: {mem_used:.2f}/{mem_limit:.2f}GB ({mem_percent:.1f}%)",
            end=""
        )

        if mem_percent > 85:
            print(" ⚠️ 内存紧张!")
        elif mem_percent > 70:
            print(" ⚡ 内存较高")
        else:
            print(" ✓")

        print(f"CPU:  {cpu_percent:.1f}%")

        # Python 进程详情
        python_procs = [
            p for p in psutil.process_iter(
                ['pid', 'name', 'memory_info', 'num_threads', 'cmdline']
            )
            if 'python' in p.info['name'].lower()
        ]

        if python_procs:
            print(f"\nPython 进程 ({len(python_procs)}):")
            total_mem = 0
            for p in python_procs:
                mem_mb = p.info['memory_info'].rss / (1024**2)
                total_mem += mem_mb
                cmdline = (
                    ' '.join(p.info['cmdline'][:2])
                    if p.info['cmdline']
                    else 'Unknown'
                )
                print(
                    f"  PID {p.info['pid']}: {mem_mb:6.1f}MB, "
                    f"{p.info['num_threads']:2d} 线程 - {cmdline[:50]}"
                )
            print(f"  总计: {total_mem:.1f}MB")

        # 网络统计
        net = psutil.net_io_counters()
        print(
            f"\n网络: ↓{net.bytes_recv/(1024**2):.1f}MB "
            f"↑{net.bytes_sent/(1024**2):.1f}MB"
        )

        time.sleep(5)


if __name__ == '__main__':
    try:
        monitor_app()
    except KeyboardInterrupt:
        print("\n\n监控已停止")
