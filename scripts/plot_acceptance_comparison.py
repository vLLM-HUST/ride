"""Plot bounded ordinary-request acceptance CSV; never label it program throughput."""
import csv
import statistics
import sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(sys.argv[1]); rows=list(csv.DictReader((root/'comparison.csv').open()))
fig,ax=plt.subplots(figsize=(7,4))
for name in ('direct','demo','request-throttling'):
    means=[statistics.mean(float(x['requests_per_second']) for x in rows if x['strategy']==name and int(x['concurrency'])==c) for c in (1,4,8)]
    ax.plot([1,4,8],means,'o-',label=name)
ax.set(xlabel='Concurrent ordinary requests',ylabel='Completed requests / second',title='RIDE real NPU bounded acceptance (64 output tokens)')
ax.legend();ax.grid(alpha=.25);fig.tight_layout()
for extension in ('png','pdf'):fig.savefig(root/('comparison.'+extension),dpi=180)
