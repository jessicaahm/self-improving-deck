## Getting started

```sh
# Activate environment
python3.13 -m venv .venv
source .venv/bin/activate 

# Installation
pip install -r requirements.txt 


# Getting Started
temporal server start-dev
python worker.py

python agents/app.py
python feedback.py "Use a dark theme with blue accents"
python feedback.py --approve
```

### Other useful CLI command
```sh
# Quickway to start workflow
temporal workflow start --type Deck \                                                                                
      --task-queue greeting-task-queue \                                                             
      --workflow-id deck-001 \                                                                       
      --input '"my-deck"' 

# Show temporal workflow
export workflowname="deck-workflow-id"
temporal workflow show --workflow-id $workflowname --detailed
```

