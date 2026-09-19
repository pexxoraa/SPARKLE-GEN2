from __future__ import annotations
import argparse,signal,time
from .background import BackgroundTaskService
from .cli import build_components
from .worker import BackgroundWorker
from .notifications import NotificationIntelligenceService

def build_worker():
    store,agent,_=build_components();service=BackgroundTaskService(store,lambda:agent,notifier=NotificationIntelligenceService(store));return BackgroundWorker(service)

def main(argv=None):
    p=argparse.ArgumentParser(prog='sparkle-background-worker');p.add_argument('--once',action='store_true');p.add_argument('--interval',type=float,default=2.0);p.add_argument('--max-tasks',type=int,default=20);a=p.parse_args(argv)
    if not .2<=a.interval<=60:raise ValueError('interval_out_of_range')
    worker=build_worker()
    if a.once:worker.run_once(max_tasks=a.max_tasks);return 0
    running=True
    def stop(*_):
        nonlocal running;running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while running:
        worker.run_once(max_tasks=a.max_tasks);time.sleep(a.interval)
    return 0

def entrypoint():return main()
if __name__=='__main__':raise SystemExit(main())
