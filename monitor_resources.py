#!/usr/bin/env python3
"""
Akash 容器资源监控脚本
监控 CPU、内存、磁盘、网络和应用进程
"""
import os
import psutil
import time
from datetime import datetime
from typing import Tuple, Dict, List

# 颜色定义
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color
    BOLD = '\033[1m'

def get_resource_limits() -> Tuple[float, float]:
    """读取 cgroup v2 资源限制"""
    try:
        # CPU 限制
        with open('/sys/fs/cgroup/cpu.max', 'r') as f:
            cpu_quota, cpu_period = map(int, f.read().strip().split())
            cpu_limit = cpu_quota / cpu_period

        # 内存限制
        with open('/sys/fs/cgroup/memory.max', 'r') as f:
            mem_limit = int(f.read().strip()) / (1024**3)
    except:
        # 降级到系统总资源
        mem_limit = psutil.virtual_memory().total / (1024**3)
        cpu_limit = psutil.cpu_count()

    return cpu_limit, mem_limit

def get_memory_usage() -> Dict[str, float]:
    """获取内存使用详情"""
    try:
        with open('/sys/fs/cgroup/memory.current', 'r') as f:
            mem_used = int(f.read().strip())
        with open('/sys/fs/cgroup/memory.max', 'r') as f:
            mem_limit = int(f.read().strip())

        # 读取内存详情
        mem_stats = {}
        with open('/sys/fs/cgroup/memory.stat', 'r') as f:
            for line in f:
                key, value = line.strip().split()
                mem_stats[key] = int(value)

        return {
            'used': mem_used / (1024**3),
            'limit': mem_limit / (1024**3),
            'percent': (mem_used / mem_limit) * 100 if mem_limit > 0 else 0,
            'anon': mem_stats.get('anon', 0) / (1024**3),  # 应用内存
            'file': mem_stats.get('file', 0) / (1024**3),  # 文件缓存
            'kernel': mem_stats.get('kernel', 0) / (1024**3),  # 内核内存
        }
    except:
        mem = psutil.virtual_memory()
        return {
            'used': mem.used / (1024**3),
            'limit': mem.total / (1024**3),
            'percent': mem.percent,
            'anon': 0,
            'file': 0,
            'kernel': 0,
        }

def get_disk_usage() -> List[Dict[str, any]]:
    """获取磁盘使用情况"""
    disks = []

    # 监控的挂载点
    mount_points = ['/', '/mnt/data', '/var/lib/postgresql', '/tmp']

    for mount_point in mount_points:
        if os.path.exists(mount_point):
            try:
                usage = psutil.disk_usage(mount_point)
                disks.append({
                    'mount': mount_point,
                    'total': usage.total / (1024**3),
                    'used': usage.used / (1024**3),
                    'free': usage.free / (1024**3),
                    'percent': usage.percent,
                })
            except:
                pass

    # 如果没有找到任何挂载点，至少返回根目录
    if not disks:
        usage = psutil.disk_usage('/')
        disks.append({
            'mount': '/',
            'total': usage.total / (1024**3),
            'used': usage.used / (1024**3),
            'free': usage.free / (1024**3),
            'percent': usage.percent,
        })

    return disks

def get_disk_io() -> Dict[str, int]:
    """获取磁盘 I/O 统计"""
    try:
        io = psutil.disk_io_counters()
        return {
            'read_mb': io.read_bytes / (1024**2),
            'write_mb': io.write_bytes / (1024**2),
            'read_count': io.read_count,
            'write_count': io.write_count,
        }
    except:
        return {
            'read_mb': 0,
            'write_mb': 0,
            'read_count': 0,
            'write_count': 0,
        }

def get_application_disk_usage() -> Dict[str, float]:
    """获取应用相关目录的磁盘使用"""
    app_dirs = {
        'logs': './logs',
        'database': './database',
        'app_root': '.',
    }

    disk_usage = {}
    for name, path in app_dirs.items():
        if os.path.exists(path):
            try:
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(path):
                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        try:
                            total_size += os.path.getsize(filepath)
                        except:
                            pass
                disk_usage[name] = total_size / (1024**2)  # MB
            except:
                disk_usage[name] = 0
        else:
            disk_usage[name] = 0

    return disk_usage

def get_python_processes() -> List[Dict[str, any]]:
    """获取 Python 进程信息"""
    python_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'num_threads', 'cmdline']):
        try:
            if 'python' in proc.info['name'].lower():
                python_procs.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cpu': proc.info['cpu_percent'],
                    'memory_mb': proc.info['memory_info'].rss / (1024**2),
                    'threads': proc.info['num_threads'],
                    'cmdline': ' '.join(proc.info['cmdline'][:3]) if proc.info['cmdline'] else 'N/A',
                })
        except:
            pass
    return python_procs

def get_network_stats() -> Dict[str, float]:
    """获取网络统计"""
    try:
        net = psutil.net_io_counters()
        return {
            'recv_mb': net.bytes_recv / (1024**2),
            'sent_mb': net.bytes_sent / (1024**2),
            'packets_recv': net.packets_recv,
            'packets_sent': net.packets_sent,
            'errors_in': net.errin,
            'errors_out': net.errout,
        }
    except:
        return {
            'recv_mb': 0,
            'sent_mb': 0,
            'packets_recv': 0,
            'packets_sent': 0,
            'errors_in': 0,
            'errors_out': 0,
        }

def format_color(value: float, warn_threshold: float, critical_threshold: float) -> str:
    """根据值返回颜色"""
    if value >= critical_threshold:
        return Colors.RED
    elif value >= warn_threshold:
        return Colors.YELLOW
    else:
        return Colors.GREEN

def print_header():
    """打印监控头部"""
    print(f"\n{Colors.BOLD}{'='*80}{Colors.NC}")
    print(f"{Colors.CYAN}{Colors.BOLD}  Hyperliquid 数据分析应用 - Akash 容器资源监控{Colors.NC}")
    print(f"{Colors.BOLD}{'='*80}{Colors.NC}")

def monitor_resources(interval: int = 5, show_details: bool = True):
    """主监控循环"""
    cpu_limit, mem_limit = get_resource_limits()

    print_header()
    print(f"\n{Colors.BLUE}容器资源限制:{Colors.NC} CPU={cpu_limit:.1f}核, 内存={mem_limit:.2f}GB")
    print(f"{Colors.BLUE}监控间隔:{Colors.NC} {interval}秒")
    print(f"{Colors.BLUE}详细模式:{Colors.NC} {'开启' if show_details else '关闭'}")

    try:
        iteration = 0
        while True:
            iteration += 1
            os.system('clear' if os.name == 'posix' else 'cls')

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n{Colors.BOLD}{'='*80}{Colors.NC}")
            print(f"{Colors.CYAN}{Colors.BOLD}  监控时间: {current_time} (第 {iteration} 次刷新){Colors.NC}")
            print(f"{Colors.BOLD}{'='*80}{Colors.NC}")

            # ==================== CPU 监控 ====================
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_color = format_color(cpu_percent, 60, 80)

            print(f"\n{Colors.BOLD}🔥 CPU:{Colors.NC}")
            print(f"  限制: {cpu_limit:.1f} 核心")
            print(f"  使用率: {cpu_color}{cpu_percent:.1f}%{Colors.NC}")

            load_avg = os.getloadavg()
            print(f"  负载: 1分钟={load_avg[0]:.2f}, 5分钟={load_avg[1]:.2f}, 15分钟={load_avg[2]:.2f}")

            # ==================== 内存监控 ====================
            mem = get_memory_usage()
            mem_color = format_color(mem['percent'], 70, 85)

            print(f"\n{Colors.BOLD}💾 内存:{Colors.NC}")
            print(f"  使用: {mem_color}{mem['used']:.2f}GB / {mem['limit']:.2f}GB ({mem['percent']:.1f}%){Colors.NC}")

            if show_details and mem['anon'] > 0:
                print(f"  详情:")
                print(f"    - 应用内存: {mem['anon']:.2f}GB")
                print(f"    - 文件缓存: {mem['file']:.2f}GB")
                print(f"    - 内核内存: {mem['kernel']:.2f}GB")

            # 内存告警
            if mem['percent'] > 85:
                print(f"  {Colors.RED}⚠️  警告: 内存使用率超过 85%!{Colors.NC}")
            elif mem['percent'] > 70:
                print(f"  {Colors.YELLOW}💡 提示: 内存使用率较高{Colors.NC}")

            # ==================== 磁盘监控 ====================
            disks = get_disk_usage()
            disk_io = get_disk_io()

            print(f"\n{Colors.BOLD}💿 磁盘使用:{Colors.NC}")
            for disk in disks:
                disk_color = format_color(disk['percent'], 70, 85)
                print(f"  {disk['mount']}:")
                print(f"    使用: {disk_color}{disk['used']:.2f}GB / {disk['total']:.2f}GB ({disk['percent']:.1f}%){Colors.NC}")
                print(f"    可用: {disk['free']:.2f}GB")

                if disk['percent'] > 85:
                    print(f"    {Colors.RED}⚠️  警告: 磁盘使用率超过 85%!{Colors.NC}")
                elif disk['percent'] > 70:
                    print(f"    {Colors.YELLOW}💡 提示: 磁盘使用率较高{Colors.NC}")

            # 磁盘 I/O
            print(f"\n{Colors.BOLD}📊 磁盘 I/O:{Colors.NC}")
            print(f"  累计读取: {disk_io['read_mb']:.1f}MB ({disk_io['read_count']:,} 次)")
            print(f"  累计写入: {disk_io['write_mb']:.1f}MB ({disk_io['write_count']:,} 次)")

            # 应用目录使用
            if show_details:
                app_disk = get_application_disk_usage()
                if any(v > 0 for v in app_disk.values()):
                    print(f"\n{Colors.BOLD}📁 应用目录占用:{Colors.NC}")
                    for name, size in app_disk.items():
                        if size > 0:
                            print(f"  {name}: {size:.2f}MB")

            # ==================== 网络监控 ====================
            net = get_network_stats()

            print(f"\n{Colors.BOLD}🌐 网络:{Colors.NC}")
            print(f"  接收: {net['recv_mb']:.1f}MB ({net['packets_recv']:,} 包)")
            print(f"  发送: {net['sent_mb']:.1f}MB ({net['packets_sent']:,} 包)")

            if net['errors_in'] > 0 or net['errors_out'] > 0:
                print(f"  {Colors.RED}错误: 接收={net['errors_in']}, 发送={net['errors_out']}{Colors.NC}")

            # ==================== 进程监控 ====================
            python_procs = get_python_processes()

            print(f"\n{Colors.BOLD}🐍 Python 进程 ({len(python_procs)}):{Colors.NC}")
            if python_procs:
                total_mem = sum(p['memory_mb'] for p in python_procs)
                total_threads = sum(p['threads'] for p in python_procs)

                for proc in python_procs[:5]:  # 只显示前5个
                    cmdline_short = proc['cmdline'][:60] + '...' if len(proc['cmdline']) > 60 else proc['cmdline']
                    print(f"  PID {proc['pid']:>6}: {proc['memory_mb']:>7.1f}MB, {proc['threads']:>3} 线程")
                    if show_details:
                        print(f"           {cmdline_short}")

                if len(python_procs) > 5:
                    print(f"  ... 还有 {len(python_procs) - 5} 个进程")

                print(f"\n  总计: {total_mem:.1f}MB, {total_threads} 线程")
            else:
                print(f"  {Colors.YELLOW}未发现 Python 进程{Colors.NC}")

            # ==================== 底部信息 ====================
            print(f"\n{Colors.BOLD}{'='*80}{Colors.NC}")
            print(f"按 Ctrl+C 退出监控 | 下次刷新: {interval}秒后")

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n{Colors.GREEN}监控已停止{Colors.NC}")
        print(f"{Colors.BOLD}{'='*80}{Colors.NC}\n")

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Akash 容器资源监控')
    parser.add_argument('-i', '--interval', type=int, default=5, help='监控刷新间隔(秒), 默认5秒')
    parser.add_argument('-s', '--simple', action='store_true', help='简化模式，隐藏详细信息')

    args = parser.parse_args()

    monitor_resources(interval=args.interval, show_details=not args.simple)
