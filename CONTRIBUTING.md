# Contributing

Thanks for your interest in contributing to emporia-collector!

## Development Setup

1. Clone the repo and create a branch:

   ```bash
   git clone https://github.com/sutterj/emporia-collector.git
   cd emporia-collector
   git checkout -b your-feature
   ```

2. Set up a Python virtual environment:

   ```bash
   cd collector
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```

3. Run the test suite:

   ```bash
   pytest --cov
   ```

## Running Locally

Copy `.env.example` to `.env` and fill in your credentials, then:

```bash
docker compose up --build
```

## Submitting Changes

1. Ensure tests pass and coverage doesn't regress.
2. Keep commits focused (one logical change per commit).
3. Open a pull request against `main` with a clear description of what and why.
4. CI must pass before merge.

## Code Style

- No external dependencies beyond `paho-mqtt`.  Auth and HTTP use stdlib only.
- Keep modules small and focused.
- Write tests for new functionality.

## Reporting Bugs

Use the [bug report template](https://github.com/sutterj/emporia-collector/issues/new?template=bug_report.md) and include:

- Docker and Python versions
- Relevant log output
- Steps to reproduce

## Questions?

Open a [discussion](https://github.com/sutterj/emporia-collector/issues) or file an issue.
