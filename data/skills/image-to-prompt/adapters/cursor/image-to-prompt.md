# Image to Prompt

Use this command to analyze one or more reference images and create faithful, reusable image-generation prompts.

First, locate and read the canonical `SKILL.md` for the `image-to-prompt` skill. Treat it as the source of truth.

Follow these rules:

1. Confirm that at least one usable reference image is available.
2. Inspect the image carefully before writing prompts.
3. Describe visible evidence: subject, composition, environment, lighting, palette, materials, and visual language.
4. Distinguish observation from inference.
5. Do not claim to know the original prompt, seed, model, lens, LoRA, checkpoint, or generation settings.
6. Do not identify real people from appearance alone.
7. Do not invent unreadable text, logos, props, scenery, or narrative details.
8. If the user names a target model, adapt the prompt structure appropriately.
9. Return the output format required by `SKILL.md`:
   - 画面拆解
   - 中文 Prompt
   - English Prompt
   - Negative Prompt, when useful
   - 建议参数
   - 可编辑变量
10. Use full-width brackets `【】` only around directly replaceable values in the editable prompt.

Ensure the Chinese and English prompts are independently usable and preserve the reference image's dominant visual structure.
