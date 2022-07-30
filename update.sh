#!/bin/bash

NOW=$(date +%Y%m%d.%H%M)
git fetch origin
git rebase origin/master
git add .
git commit -m "$NOW"
git push origin HEAD

