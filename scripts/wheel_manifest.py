"""Record checksums of the prepared, platform-specific offline installation bundle."""
import hashlib
import json
import platform
import sys
from pathlib import Path

directory=Path(sys.argv[1])
report={'python':platform.python_version(),'platform':platform.platform(),
        'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob('*.whl'))}}
(directory/'manifest.json').write_text(json.dumps(report,indent=2))
print(f"Manifest written for {len(report['files'])} wheels")
