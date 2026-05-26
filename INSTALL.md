# Install & Run on Your Mac

## 1. Set up the project

```bash
cd ~/Desktop/ai-news-aggregator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Gmail app password (for email digests)
```

## 2. Run the web dashboard

```bash
PORT=8080 python3 run.py
```

Open **http://127.0.0.1:8080/feed**

## 3. Or run the CLI digest

```bash
python3 -m core.main morning
python3 -m core.main morning --send   # also email it
```

## 4. Run tests (optional)

```bash
python3 -m pytest tests/ -q
```
