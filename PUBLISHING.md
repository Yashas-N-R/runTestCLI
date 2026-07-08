# Publishing nltest to PyPI (maintainers)

End users install with:

```bash
pip install nltest
```

## One-time setup

1. Create an account at https://pypi.org
2. Create an API token (scope: entire account or project `nltest`)
3. In GitHub repo **Settings → Secrets → Actions**, add `PYPI_API_TOKEN`
4. Create a GitHub **Environment** named `pypi` (optional but recommended) and require approval for publishes

## Publish a release

1. Bump `version` in `pyproject.toml`
2. Commit and push to `main`
3. Create a GitHub Release (tag e.g. `v0.2.0`) — this triggers `.github/workflows/publish.yml`
4. The workflow downloads the embedding model, builds the wheel (model included), and uploads to PyPI

Or run manually: **Actions → Publish to PyPI → Run workflow**

## Local wheel build (smoke test)

```bash
pip install build huggingface_hub
python scripts/bundle_embedding_model.py
python -m build
pip install dist/nltest-*.whl
nltest --help
```

The wheel should be ~90–120 MB because it contains the bundled MiniLM weights.
