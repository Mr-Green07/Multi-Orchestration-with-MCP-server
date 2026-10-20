import logging
import os 
import sys 
from pathlib import Path 


#Rule 1: Logger Redirect go to stderr
logging.basicConfig(
    level = logging.INFO,
    stream = sys.stderr,
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
   force = True,
)


#Rule 2: Sandbox Root a workspace jail root
WORKSPACE_JAIL_ROOT = Path(
    os.environ.get(
        "WORKSPACE_JAIL_ROOT",
        "~/AgentWorkSpace",
    )
).expanduser().resolve()


WORKSPACE_JAIL_ROOT.mkdir(parents = True, exist_ok = True)
