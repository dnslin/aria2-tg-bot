import os
import sys
import time
import signal
import logging
import subprocess
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class BotReloader(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.should_reload = False
        self.last_reload = 0
        
    def kill_bot_processes(self):
        """杀死所有相关的Python进程"""
        current_pid = os.getpid()
        current_process = psutil.Process(current_pid)
        
        # 获取当前进程的所有子进程
        children = current_process.children(recursive=True)
        
        # 遍历所有进程
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # 跳过当前进程
                if proc.pid == current_pid:
                    continue
                    
                # 如果是Python进程且命令行包含bot.py
                if proc.name() == 'python' and any('bot.py' in cmd for cmd in proc.cmdline()):
                    logging.info(f"🔪 终止进程 {proc.pid}")
                    # 发送SIGTERM信号
                    os.kill(proc.pid, signal.SIGTERM)
                    # 等待进程结束
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        # 如果等待超时，强制结束进程
                        os.kill(proc.pid, signal.SIGKILL)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
    def start_bot(self):
        """启动机器人进程"""
        try:
            # 先终止所有相关进程
            self.kill_bot_processes()
            
            # 等待一段时间确保进程完全终止
            time.sleep(2)
            
            logging.info("🔄 启动机器人...")
            self.process = subprocess.Popen([sys.executable, "bot.py"])
            self.last_reload = time.time()
        except Exception as e:
            logging.error(f"启动机器人失败: {str(e)}")
        
    def stop_bot(self):
        """停止机器人进程"""
        if self.process:
            logging.info("⏹ 停止机器人...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            
    def on_modified(self, event):
        """文件修改事件处理"""
        if event.src_path.endswith('.py'):
            # 防止短时间内多次重启
            if time.time() - self.last_reload > 2:
                logging.info(f"📝 检测到文件变化: {event.src_path}")
                self.should_reload = True
                
    def run(self):
        """运行热更新管理器"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 设置监控目录
        path = os.path.dirname(os.path.abspath(__file__))
        observer = Observer()
        observer.schedule(self, path, recursive=True)
        observer.start()
        
        logging.info("🔍 开始监控文件变化...")
        self.start_bot()
        
        try:
            while True:
                if self.should_reload:
                    self.start_bot()
                    self.should_reload = False
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            self.stop_bot()
            logging.info("👋 停止服务")
            
        observer.join()
        
if __name__ == "__main__":
    reloader = BotReloader()
    reloader.run() 