# Git workflow (per phase)

```bash
git status
git switch main
git pull --ff-only origin main
git switch -c phase-NN-name
# ...implement and test...
git status
git add -A
git diff --cached
git commit -m "feat(phase-NN): message"
git push -u origin phase-NN-name
```
Open the pull request on GitHub (base `main`, compare `phase-NN-name`), or with `gh pr create`.
After verification, merge, then `git switch main && git pull --ff-only origin main`.
Never commit `.env`, `node_modules`, virtual environments or generated datasets/models.
