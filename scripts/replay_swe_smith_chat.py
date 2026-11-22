#!/usr/bin/env python3
"""Run a pinned SWE-smith replay through program-aware chat completions."""

import runpy
from pathlib import Path
import sys


def rendered_chat_prompt(self, token_ids):
    # Chat sends text. Encoding that text can merge tokens where the previous
    # model output joins synthetic tool input. Do not change the transmitted
    # text or report the pre-render token IDs as what the engine received.
    return self.tokenizer.apply_chat_template(
        [{"role": "user", "content": self.text(token_ids)}],
        add_generation_prompt=True, tokenize=True, return_dict=False,
        **self.chat_template_kwargs,
    )


def main():
    path = Path(sys.argv[1]).resolve()
    sys.argv = [str(path), *sys.argv[2:]]
    sys.path.insert(0, str(path.parent))
    replay = runpy.run_path(str(path))
    replay["ChatRendering"].rendered_prompt_token_ids = rendered_chat_prompt
    print("SWE-smith chat replay validates the tokens of the transmitted text.", flush=True)
    replay["main"]()


if __name__ == "__main__":
    main()
