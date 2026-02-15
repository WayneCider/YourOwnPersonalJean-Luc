"""Chat template system for multi-model support.

Defines prompt formatting for different model families. Each template specifies
how to wrap system, user, and assistant messages, plus the generation prefix
and stop tokens.

Supports auto-detection from model filenames (e.g., "qwen" → chatml, "llama" → llama3).
Manual override via --template flag.
"""

from dataclasses import dataclass, field


@dataclass
class ChatTemplate:
    """Defines prompt formatting for a model family."""
    name: str
    # Format strings — {content} is replaced with the message text
    system_fmt: str
    user_fmt: str
    assistant_fmt: str
    # Prefix appended at the end to prompt generation
    generation_prefix: str
    # Stop tokens the model uses to signal end of turn
    stop_tokens: list[str] = field(default_factory=list)
    # Description for --help output
    description: str = ""


# ============================================================
# Template definitions
# ============================================================

CHATML = ChatTemplate(
    name="chatml",
    system_fmt="<|im_start|>system\n{content}<|im_end|>",
    user_fmt="<|im_start|>user\n{content}<|im_end|>",
    assistant_fmt="<|im_start|>assistant\n{content}<|im_end|>",
    generation_prefix="<|im_start|>assistant\n",
    stop_tokens=["<|im_end|>", "<|im_start|>"],
    description="ChatML (Qwen, DeepSeek, OpenHermes, Nous)",
)

LLAMA3 = ChatTemplate(
    name="llama3",
    system_fmt="<|start_header_id|>system<|end_header_id|>\n\n{content}<|eot_id|>",
    user_fmt="<|start_header_id|>user<|end_header_id|>\n\n{content}<|eot_id|>",
    assistant_fmt="<|start_header_id|>assistant<|end_header_id|>\n\n{content}<|eot_id|>",
    generation_prefix="<|start_header_id|>assistant<|end_header_id|>\n\n",
    stop_tokens=["<|eot_id|>", "<|start_header_id|>"],
    description="Llama 3 / 3.1 / 3.2 / 3.3",
)

LLAMA2 = ChatTemplate(
    name="llama2",
    system_fmt="<<SYS>>\n{content}\n<</SYS>>",
    user_fmt="[INST] {content} [/INST]",
    assistant_fmt="{content}",
    generation_prefix="",
    stop_tokens=["[INST]", "</s>"],
    description="Llama 2 / CodeLlama / Mistral v0.1",
)

MISTRAL = ChatTemplate(
    name="mistral",
    system_fmt="[INST] {content}\n",
    user_fmt="[INST] {content} [/INST]",
    assistant_fmt="{content}</s>",
    generation_prefix="",
    stop_tokens=["</s>", "[INST]"],
    description="Mistral v0.2+ / Mixtral",
)

GEMMA = ChatTemplate(
    name="gemma",
    system_fmt="<start_of_turn>user\n{content}<end_of_turn>",
    user_fmt="<start_of_turn>user\n{content}<end_of_turn>",
    assistant_fmt="<start_of_turn>model\n{content}<end_of_turn>",
    generation_prefix="<start_of_turn>model\n",
    stop_tokens=["<end_of_turn>", "<start_of_turn>"],
    description="Gemma / Gemma 2 / CodeGemma",
)

PHI3 = ChatTemplate(
    name="phi3",
    system_fmt="<|system|>\n{content}<|end|>",
    user_fmt="<|user|>\n{content}<|end|>",
    assistant_fmt="<|assistant|>\n{content}<|end|>",
    generation_prefix="<|assistant|>\n",
    stop_tokens=["<|end|>", "<|user|>"],
    description="Phi-3 / Phi-3.5",
)

COMMAND_R = ChatTemplate(
    name="command-r",
    system_fmt="<|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|>{content}<|END_OF_TURN_TOKEN|>",
    user_fmt="<|START_OF_TURN_TOKEN|><|USER_TOKEN|>{content}<|END_OF_TURN_TOKEN|>",
    assistant_fmt="<|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>{content}<|END_OF_TURN_TOKEN|>",
    generation_prefix="<|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>",
    stop_tokens=["<|END_OF_TURN_TOKEN|>"],
    description="Cohere Command-R / Command-R+",
)

ZEPHYR = ChatTemplate(
    name="zephyr",
    system_fmt="<|system|>\n{content}</s>",
    user_fmt="<|user|>\n{content}</s>",
    assistant_fmt="<|assistant|>\n{content}</s>",
    generation_prefix="<|assistant|>\n",
    stop_tokens=["</s>", "<|user|>"],
    description="Zephyr / StableLM-Zephyr",
)

ALPACA = ChatTemplate(
    name="alpaca",
    system_fmt="{content}\n",
    user_fmt="### Instruction:\n{content}\n",
    assistant_fmt="### Response:\n{content}\n",
    generation_prefix="### Response:\n",
    stop_tokens=["### Instruction:", "###"],
    description="Alpaca / Vicuna / generic instruct",
)

# ============================================================
# Registry
# ============================================================

TEMPLATES: dict[str, ChatTemplate] = {
    t.name: t for t in [
        CHATML, LLAMA3, LLAMA2, MISTRAL, GEMMA, PHI3, COMMAND_R, ZEPHYR, ALPACA,
    ]
}

# Filename patterns → template name (checked in order, first match wins)
_FILENAME_PATTERNS: list[tuple[str, str]] = [
    # Specific models first
    ("qwen", "chatml"),
    ("deepseek", "chatml"),
    ("openhermes", "chatml"),
    ("nous", "chatml"),
    ("yi-", "chatml"),
    ("internlm", "chatml"),
    ("llama-3", "llama3"),
    ("llama3", "llama3"),
    ("meta-llama-3", "llama3"),
    ("llama-2", "llama2"),
    ("llama2", "llama2"),
    ("codellama", "llama2"),
    ("mistral", "mistral"),
    ("mixtral", "mixtral"),  # Mistral variant, same template
    ("gemma", "gemma"),
    ("codegemma", "gemma"),
    ("phi-3", "phi3"),
    ("phi3", "phi3"),
    ("command-r", "command-r"),
    ("zephyr", "zephyr"),
    ("stablelm", "zephyr"),
    ("vicuna", "alpaca"),
    ("alpaca", "alpaca"),
]

# Fix mixtral → use mistral template (same format)
_FILENAME_PATTERNS = [(p, "mistral" if n == "mixtral" else n) for p, n in _FILENAME_PATTERNS]


def get_template(name: str) -> ChatTemplate:
    """Get a template by name. Raises KeyError if not found."""
    if name not in TEMPLATES:
        available = ", ".join(sorted(TEMPLATES.keys()))
        raise KeyError(f"Unknown template '{name}'. Available: {available}")
    return TEMPLATES[name]


def detect_template(model_path: str) -> ChatTemplate:
    """Auto-detect template from model filename.

    Scans the filename for known model family keywords.
    Falls back to ChatML if no match (most common format).
    """
    filename = model_path.lower().replace("\\", "/").split("/")[-1]

    for pattern, template_name in _FILENAME_PATTERNS:
        if pattern in filename:
            return TEMPLATES[template_name]

    # Default to ChatML — most widely used instruct format
    return CHATML


def build_prompt(
    messages: list[dict],
    template: ChatTemplate,
    system_prompt: str = None,
    max_chars: int = 0,
) -> str:
    """Build a formatted prompt from conversation messages using the given template.

    Args:
        messages: List of {role, content} dicts.
        template: ChatTemplate defining the format.
        system_prompt: Optional system prompt text.
        max_chars: If > 0, enforce character budget by dropping oldest messages.

    Returns:
        Formatted prompt string ready for the model.
    """
    system_part = ""
    if system_prompt:
        system_part = template.system_fmt.format(content=system_prompt) + "\n"

    overhead = len(system_part) + len(template.generation_prefix) + 50

    msg_parts = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "tool_result":
            role = "user"  # Tool results injected as user messages

        if role == "system":
            msg_parts.append(template.system_fmt.format(content=content))
        elif role == "user":
            msg_parts.append(template.user_fmt.format(content=content))
        elif role == "assistant":
            msg_parts.append(template.assistant_fmt.format(content=content))
        else:
            # Unknown role — treat as user
            msg_parts.append(template.user_fmt.format(content=content))

    # Enforce character budget by dropping oldest messages
    if max_chars > 0:
        budget = max_chars - overhead
        while len(msg_parts) > 2:
            total = sum(len(p) for p in msg_parts)
            if total <= budget:
                break
            msg_parts.pop(0)

    return system_part + "\n".join(msg_parts) + "\n" + template.generation_prefix


def list_templates() -> list[dict]:
    """Return template info for display."""
    return [
        {"name": t.name, "description": t.description}
        for t in TEMPLATES.values()
    ]
