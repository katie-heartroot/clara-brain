#!/bin/bash
# Clara Daemon entrypoint for Fly.io
# Syncs brain files to persistent volume, then starts daemon

BRAIN_SRC="/app/brain"
BRAIN_DST="/data/brain"

# Create directories on persistent volume
mkdir -p "$BRAIN_DST/memory" "$BRAIN_DST/sessions" "$BRAIN_DST/images/thumbs"

# Sync brain files (don't overwrite sessions — those are live data)
for f in CLARA-SOUL.md CONTEXT.md GOALS.md WINS.md NEXT.md MEMORY.md BOOTSTRAP.md README.md knowledge.json; do
    cp "$BRAIN_SRC/$f" "$BRAIN_DST/$f" 2>/dev/null || true
done

# Sync memory files (only if they don't exist yet on volume)
for f in RECENT.md PINNED.md SUMMARY.md ORIGINS.md; do
    if [ ! -f "$BRAIN_DST/memory/$f" ]; then
        cp "$BRAIN_SRC/memory/$f" "$BRAIN_DST/memory/$f" 2>/dev/null || true
    fi
done

# ORIGINS.md is sacred — always update it from source
cp "$BRAIN_SRC/memory/ORIGINS.md" "$BRAIN_DST/memory/ORIGINS.md" 2>/dev/null || true

# Seed images.json with from-ryan images if it doesn't exist yet
if [ ! -f "$BRAIN_DST/images/images.json" ]; then
    cp "$BRAIN_SRC/images-seed.json" "$BRAIN_DST/images/images.json" 2>/dev/null || true
    echo "Seeded images.json with from-ryan collection."
else
    # Merge: add any seed entries whose IDs aren't already present
    python3 -c "
import json, sys
try:
    seed = json.load(open('$BRAIN_SRC/images-seed.json'))
    live = json.load(open('$BRAIN_DST/images/images.json'))
    existing_ids = {i.get('id') for i in live}
    added = 0
    for item in seed:
        if item.get('id') not in existing_ids:
            live.append(item)
            added += 1
    if added:
        json.dump(live, open('$BRAIN_DST/images/images.json', 'w'), indent=2)
        print(f'Merged {added} new seed images into images.json')
    else:
        print('All seed images already present.')
except Exception as e:
    print(f'Seed merge skipped: {e}')
"
fi

echo "Brain synced to persistent volume."
echo "Starting Clara daemon..."

exec python -u /app/app/clara_daemon.py
