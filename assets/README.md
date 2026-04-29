# Assets Directory

Place images and brand assets here for use in Patreon and other publisher posts.

## Structure

- **brand/** — Logo, mascot (Glido the flying squirrel), and global brand assets used across all posts.
- **patreon/** — Patreon-specific templates, headers, and post banners.
- **deals/** — Optional: destination hero images or deal-specific visuals pulled from tracker or external sources.

## Usage in Patreon Publisher

In `app/publishers/patreon.py`, reference images:

```python
import os
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"

# Example: attach brand mascot
mascot_path = ASSETS_DIR / "brand" / "glido.png"
if mascot_path.exists():
    # Upload to Patreon or embed in HTML
```

## Image Guidelines

- Format: PNG, JPG (recommended for web)
- Size: Keep file sizes < 5 MB for faster publishing
- Patreon post images: ~1200x630px (optimal for sharing)
- Brand mascot (Glido): ~500x500px for headers/footers
- Naming: Use lowercase with underscores (e.g., `glido_mascot.png`, `patreon_header.png`)

## Git Handling

Images are tracked in Git. If adding large media, consider:

- Using Git LFS (Large File Storage) for files > 50 MB
- Optimize images before committing (compress, resize)
