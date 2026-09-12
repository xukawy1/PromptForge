# Image to Prompt

An open Agent Skill for reconstructing faithful, reusable image-generation prompts from reference images.

## What it does

This skill analyzes one or more images from visible evidence and produces practical prompts for image-generation models.

It helps you:

- Break down subject, composition, lighting, color, materials, and visual style
- Create copy-ready Chinese and English reconstruction prompts
- Produce model-specific prompt guidance for Midjourney, Stable Diffusion, SDXL, FLUX, and DALL-E
- Generate relevant negative prompts and recommended starting parameters
- Provide a complete editable prompt with directly replaceable values

## Core principle

> Reconstruct prompts from visible evidence, not hidden generation settings.

The skill distinguishes observation from inference. It does not claim to recover an original prompt, seed, model, lens, LoRA, checkpoint, or other undocumented generation setting.

## Supported image types

- Photography and portraits
- Illustration and anime
- 3D renders and product images
- Posters and editorial graphics
- UI screenshots
- Architecture and interior images
- Mixed-media and highly stylized visuals

## Default output

For each reference image, the skill provides:

1. A compact visual breakdown
2. A polished Chinese prompt
3. A polished English prompt
4. A relevant negative prompt, when useful
5. Recommended starting parameters
6. A complete editable Chinese prompt using `【】` around replaceable values

## Installation

### Codex

Clone the complete skill directory:

```bash
git clone https://github.com/jiemianduan/image-to-prompt.git \
  ~/.codex/skills/image-to-prompt
```

Then invoke:

```text
$image-to-prompt
```

### Cursor

Copy `adapters/cursor/image-to-prompt.md` into your project's:

```text
.cursor/commands/image-to-prompt.md
```

Then use `/image-to-prompt` in Cursor Chat
