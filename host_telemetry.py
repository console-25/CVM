"""Bounded, process-wide host samples; no invented zero on collection failure."""
import threading
import time
from pathlib import Path

class HostTelemetry:
    def __init__(self):self.lock=threading.Lock();self.previous=None;self.cached=None
    def sample(self):
        import psutil
        with self.lock:
            now=time.monotonic()
            if self.cached and now-self.cached['_sampled']<5:return {k:v for k,v in self.cached.items() if not k.startswith('_')}
            cpu=psutil.cpu_times();total=sum(cpu)-getattr(cpu,'guest',0)-getattr(cpu,'guest_nice',0);idle=cpu.idle+getattr(cpu,'iowait',0)
            interface=None
            try:
                for line in Path('/proc/net/route').read_text().splitlines()[1:]:
                    fields=line.split()
                    if fields[1]=='00000000' and int(fields[3],16)&2:interface=fields[0];break
            except (OSError,ValueError,IndexError):pass
            counter=psutil.net_io_counters(pernic=True).get(interface)
            transferred=counter.bytes_recv+counter.bytes_sent if counter else None
            cpu_pct=network=None
            if self.previous:
                before=self.previous;elapsed=now-before['time'];total_delta=total-before['total']
                if total_delta>0:cpu_pct=max(0,min(100,100*(1-(idle-before['idle'])/total_delta)))
                if transferred is not None and before['bytes'] is not None and before['interface']==interface and transferred>=before['bytes'] and elapsed>0:
                    network=(transferred-before['bytes'])/elapsed
            self.previous={'time':now,'total':total,'idle':idle,'bytes':transferred,'interface':interface}
            self.cached={'success':True,'timestamp':time.time(),'cpu':cpu_pct,'memory':psutil.virtual_memory().percent,'disk':psutil.disk_usage('/').percent,'network':network,'interface':interface,'_sampled':now}
            return {k:v for k,v in self.cached.items() if not k.startswith('_')}
