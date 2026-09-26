import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

def estimate_tokens(text: str) -> int:
    """
    Estimates token count using the ~4 characters per token heuristic
    (128 tokens ≈ 512 chars, 400 tokens ≈ 1,600 chars, 64 tokens ≈ 256 chars).
    """
    if not text:
        return 0
    return max(1, (len(text.strip()) + 3) // 4)


@dataclass
class MarkdownChunk:
    chunk_id: str
    text: str
    raw_content: str
    doc_title: str
    file_path: str
    heading: str
    tags: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    line_start: int = 1
    line_end: int = 1
    chunk_index: int = 0
    clearance_level: int = 0
    boundary_type: str = "header"
    token_estimate: int = 0

    def __post_init__(self) -> None:
        if self.token_estimate <= 0:
            self.token_estimate = estimate_tokens(self.raw_content or self.text)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, item: str) -> bool:
        if hasattr(self, item):
            return True
        return item in self.text or item in self.raw_content


# Alias Chunk for callers expecting Chunk dataclass directly
Chunk = MarkdownChunk

# Regex patterns for atomic formula and code block preservation (never split inside)
_PROTECTED_BLOCK_REGEX = re.compile(
    r'(```[\s\S]*?```|\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])'
)
_MATH_BLOCK_REGEX = re.compile(
    r'(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])'
)


def _find_protected_spans(text: str) -> List[Tuple[int, int, str]]:
    """
    Returns a sorted list of (start_idx, end_idx, block_type) for atomic blocks
    that must never be split mid-block:
      - Fenced code blocks: ```...```
      - LaTeX display math blocks: $$...$$ and \\[...\\]
    """
    spans: List[Tuple[int, int, str]] = []
    for match in _PROTECTED_BLOCK_REGEX.finditer(text):
        s, e = match.span()
        snippet = match.group(0)
        btype = "code" if snippet.startswith("```") else "math"
        spans.append((s, e, btype))
    return spans


def _is_inside_protected_span(idx: int, spans: List[Tuple[int, int, str]]) -> Optional[Tuple[int, int, str]]:
    """Returns the enclosing (start, end, type) if idx is strictly inside a protected span."""
    for s, e, btype in spans:
        if s < idx < e:
            return (s, e, btype)
    return None


def dynamic_syntactic_chunk_text(
    text: str,
    min_tokens: int = 128,
    max_tokens: int = 400,
    overlap_tokens: int = 64,
    default_boundary_type: str = "header",
    doc_title: str = "Document",
    filepath: str = "doc.md",
    heading: str = "",
    start_line: int = 1,
    chunk_index_offset: int = 0,
    clearance_level: int = 0,
    tags: Optional[List[str]] = None,
    aliases: Optional[List[str]] = None,
) -> List[MarkdownChunk]:
    """
    Chapter 24 Dynamic Syntactic Clause-Boundary Windowing.
    Replaces rigid rectangular token cuts with a syntactic boundary detector
    operating over a [min_tokens, max_tokens] (~512 to ~1,600 chars) target window
    with a sliding overlap_tokens (~64 tokens / ~256 chars) window.

    Syntactic Snap Priority:
      1. Paragraph boundaries (\\n\\n)
      2. Markdown sub-headers (\\n#) or list boundaries
      3. Formula / Code block preservation (never split inside $$...$$, \\[...\\], or ```...```)
      4. Clause & Sentence delimiters ([.!?]\\s+, ;\\s+)
    """
    cleaned = text.strip()
    if not cleaned:
        return []

    min_chars = max(64, min_tokens * 4)
    max_chars = max(min_chars + 64, max_tokens * 4)
    overlap_chars = max(0, overlap_tokens * 4)

    protected_spans = _find_protected_spans(cleaned)
    n = len(cleaned)

    raw_windows: List[Tuple[str, str, int, int]] = []  # (chunk_raw_text, boundary_type, char_start, char_end)

    if n <= max_chars:
        has_math = bool(_MATH_BLOCK_REGEX.search(cleaned))
        btype = "math_preserved" if has_math else default_boundary_type
        raw_windows.append((cleaned, btype, 0, n))
    else:
        cursor = 0
        while cursor < n:
            remaining = n - cursor
            if remaining <= max_chars:
                sub_text = cleaned[cursor:].strip()
                if sub_text:
                    has_math = bool(_MATH_BLOCK_REGEX.search(sub_text))
                    btype = "math_preserved" if has_math else default_boundary_type
                    raw_windows.append((sub_text, btype, cursor, n))
                break

            window_min = min(n, cursor + min_chars)
            window_max = min(n, cursor + max_chars)
            math_extended = False

            # Check if window_max lands inside a protected LaTeX math or code block
            enclosing = _is_inside_protected_span(window_max, protected_spans)
            if enclosing is not None:
                span_start, span_end, span_type = enclosing
                # Prefer snapping cleanly BEFORE the block if it starts at or after window_min
                # AND is not at the very start of our current chunk
                if span_start >= window_min and span_start > cursor:
                    window_max = span_start
                    if span_type == "math":
                        math_extended = True
                else:
                    # Extend window_max to include the entire protected block intact
                    window_max = span_end
                    if span_type == "math":
                        math_extended = True

            # Search for highest-priority syntactic boundary in [window_min, window_max]
            # outside of any protected spans
            cut_idx: Optional[int] = None
            snap_type: str = "clause"

            # Priority 1: Paragraph boundaries (\n\n+)
            best_para = None
            for m in re.finditer(r'\n\s*\n', cleaned[cursor:window_max]):
                cand = cursor + m.end()
                if cand >= window_min and _is_inside_protected_span(cand, protected_spans) is None:
                    best_para = cand
            if best_para is not None:
                cut_idx = best_para
                snap_type = "paragraph"

            # Priority 2: Markdown sub-headers (\n#) or list boundaries (\n- , \n* , \n1. )
            if cut_idx is None:
                best_hdr = None
                best_hdr_type = "header"
                for m in re.finditer(r'\n(?:#{1,6}\s+|(?:[-*+]|\d+\.)\s+)', cleaned[cursor:window_max]):
                    cand = cursor + m.start() + 1  # cut right at the newline before header/list
                    if cand >= window_min and _is_inside_protected_span(cand, protected_spans) is None:
                        best_hdr = cand
                        best_hdr_type = "header" if m.group(0).lstrip().startswith("#") else "paragraph"
                if best_hdr is not None:
                    cut_idx = best_hdr
                    snap_type = best_hdr_type

            # Priority 3: If we extended around a protected block right at window_max
            if cut_idx is None and math_extended and _is_inside_protected_span(window_max, protected_spans) is None:
                cut_idx = window_max
                snap_type = "math_preserved"

            # Priority 4: Clause & Sentence delimiters ([.!?]\s+, ;\s+)
            if cut_idx is None:
                best_clause = None
                for m in re.finditer(r'(?:[.!?]+|;)\s+', cleaned[cursor:window_max]):
                    cand = cursor + m.end()
                    if cand >= window_min and _is_inside_protected_span(cand, protected_spans) is None:
                        best_clause = cand
                if best_clause is not None:
                    cut_idx = best_clause
                    snap_type = "clause"

            # Fallback: Nearest whitespace outside protected spans
            if cut_idx is None:
                for m in re.finditer(r'\s+', cleaned[cursor:window_max]):
                    cand = cursor + m.end()
                    if cand > cursor and _is_inside_protected_span(cand, protected_spans) is None:
                        cut_idx = cand
                if cut_idx is None:
                    # If still inside a giant protected block, jump to its end
                    encl = _is_inside_protected_span(window_max, protected_spans)
                    cut_idx = encl[1] if encl else window_max
                    snap_type = "math_preserved" if (encl and encl[2] == "math") else "clause"

            sub_text = cleaned[cursor:cut_idx].strip()
            if sub_text:
                has_math = bool(_MATH_BLOCK_REGEX.search(sub_text))
                final_btype = "math_preserved" if (has_math or math_extended or snap_type == "math_preserved") else snap_type
                raw_windows.append((sub_text, final_btype, cursor, cut_idx))

            if cut_idx >= n:
                break

            # Compute next cursor with sliding overlap (~64 tokens / ~256 chars)
            if overlap_chars > 0 and (cut_idx - cursor) > overlap_chars:
                target_overlap_start = max(cursor + 1, cut_idx - overlap_chars)
                # Ensure overlap start never slices into a protected math/code block
                ov_encl = _is_inside_protected_span(target_overlap_start, protected_spans)
                if ov_encl is not None:
                    # Start either before the protected block (if > cursor) or after it (at cut_idx)
                    if ov_encl[0] > cursor:
                        next_cursor = ov_encl[0]
                    else:
                        next_cursor = min(cut_idx, ov_encl[1])
                else:
                    # Snap overlap start to a clean clause, sentence, paragraph, or word boundary
                    overlap_slice = cleaned[target_overlap_start:cut_idx]
                    clause_m = re.search(r'(?:\n\s*\n|(?:[.!?]+|;)\s+)', overlap_slice)
                    if clause_m and _is_inside_protected_span(target_overlap_start + clause_m.end(), protected_spans) is None:
                        next_cursor = target_overlap_start + clause_m.end()
                    else:
                        ws_m = re.search(r'\s+', overlap_slice)
                        if ws_m and _is_inside_protected_span(target_overlap_start + ws_m.end(), protected_spans) is None:
                            next_cursor = target_overlap_start + ws_m.end()
                        else:
                            next_cursor = cut_idx
            else:
                next_cursor = cut_idx

            if next_cursor <= cursor:
                next_cursor = cut_idx
            cursor = next_cursor

    # Materialize MarkdownChunk objects with accurate line tracking and breadcrumbs
    result_chunks: List[MarkdownChunk] = []
    effective_heading = heading or doc_title
    for idx, (sub_raw, btype, c_start, c_end) in enumerate(raw_windows):
        line_offset_start = start_line + cleaned[:c_start].count("\n")
        line_offset_end = start_line + cleaned[:c_end].count("\n")

        if effective_heading and effective_heading != doc_title:
            breadcrumb_header = f"[Doc: {doc_title} > {effective_heading}]"
        else:
            breadcrumb_header = f"[Doc: {doc_title}]"
        full_text = f"{breadcrumb_header}\n\n{sub_raw}"

        c_idx = chunk_index_offset + idx
        result_chunks.append(
            MarkdownChunk(
                chunk_id=f"{filepath}#{c_idx}",
                text=full_text,
                raw_content=sub_raw,
                doc_title=doc_title,
                file_path=filepath,
                heading=effective_heading,
                tags=list(tags or []),
                aliases=list(aliases or []),
                line_start=line_offset_start,
                line_end=max(line_offset_start, line_offset_end),
                chunk_index=c_idx,
                clearance_level=clearance_level,
                boundary_type=btype,
                token_estimate=estimate_tokens(sub_raw),
            )
        )

    return result_chunks


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str, int]:
    """
    Extracts YAML frontmatter delimited by '---' at the very beginning of the document.
    Returns: (metadata_dict, body_content, line_offset)
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, content, 0

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return {}, content, 0

    frontmatter_raw = "".join(lines[1:end_idx])
    try:
        metadata = yaml.safe_load(frontmatter_raw) or {}
    except Exception:
        metadata = {}

    body = "".join(lines[end_idx + 1:])
    # frontmatter ends at end_idx + 1 (1-based line count)
    return metadata, body, end_idx + 1


def split_into_header_sections(body: str, line_offset: int) -> List[Dict[str, Any]]:
    """
    Splits markdown body into sections based on markdown headers (#, ##, ###, etc.).
    Preserves line tracking and header level hierarchy, ignoring '#' inside code fences.
    """
    lines = body.splitlines()
    sections = []
    
    current_lines = []
    current_start_line = line_offset + 1
    current_header = ""
    current_level = 0
    in_code_block = False

    header_regex = re.compile(r'^(#{1,6})\s+(.*)$')

    for idx, line in enumerate(lines):
        line_num = line_offset + idx + 1
        if line.strip().startswith("```"):
            in_code_block = not in_code_block

        match = header_regex.match(line) if not in_code_block else None
        if match:
            # Start of a new header
            if current_lines:
                sections.append({
                    "header": current_header,
                    "level": current_level,
                    "lines": current_lines,
                    "start_line": current_start_line,
                    "end_line": line_num - 1
                })
                current_lines = []
            current_level = len(match.group(1))
            current_header = match.group(2).strip()
            current_start_line = line_num
            current_lines.append(line)
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "header": current_header,
            "level": current_level,
            "lines": current_lines,
            "start_line": current_start_line,
            "end_line": line_offset + len(lines)
        })

    return sections


def split_large_section(lines: List[str], max_chars: int = 1500) -> List[List[str]]:
    """
    Sub-splits a list of lines on syntactic/paragraph breaks while respecting fenced code
    and display math blocks. Maintained for backward compatibility.
    """
    joined = "\n".join(lines)
    if len(joined) <= max_chars:
        return [lines]
    max_toks = max(32, max_chars // 4)
    min_toks = max(16, min(128, max_toks // 3))
    sub_chunks = dynamic_syntactic_chunk_text(
        joined,
        min_tokens=min_toks,
        max_tokens=max_toks,
        overlap_tokens=min(64, min_toks // 2),
    )
    return [c.raw_content.splitlines() for c in sub_chunks] if sub_chunks else [lines]


def parse_and_chunk_markdown(
    content: str,
    filepath: str = "doc.md",
    max_chunk_chars: int = 1600,
    min_chunk_tokens: int = 128,
    max_chunk_tokens: Optional[int] = None,
    overlap_tokens: int = 64,
) -> List[MarkdownChunk]:
    """
    Parses YAML frontmatter, extracts heading hierarchy, injects breadcrumbs,
    applies Dynamic Syntactic Clause-Boundary Windowing when sections exceed the
    target window, and returns a list of MarkdownChunk objects with line-level accuracy.
    """
    metadata, body, line_offset = parse_frontmatter(content)
    
    # Determine doc title
    doc_title = metadata.get("title")
    if not doc_title:
        # Fallback: search for first # Title in body
        h1_match = re.search(r'^#\s+(.*)$', body, re.MULTILINE)
        if h1_match:
            doc_title = h1_match.group(1).strip()
        else:
            doc_title = Path(filepath).stem.replace("_", " ").replace("-", " ").title()

    # Determine document clearance level
    from .security import ClearanceLevel
    doc_clearance_raw = (
        metadata.get("clearance")
        or metadata.get("clearance_level")
        or metadata.get("security_level")
        or 0
    )
    try:
        doc_clearance = ClearanceLevel.from_string(doc_clearance_raw).value
    except Exception:
        doc_clearance = 0

    tags = metadata.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    aliases = metadata.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]

    effective_max_tokens = max_chunk_tokens if max_chunk_tokens is not None else max(32, max_chunk_chars // 4)
    effective_min_tokens = min(min_chunk_tokens, max(16, effective_max_tokens // 2))

    raw_sections = split_into_header_sections(body, line_offset)
    
    chunks: List[MarkdownChunk] = []
    heading_stack: Dict[int, str] = {}
    chunk_counter = 0

    for sec in raw_sections:
        level = sec["level"]
        header = sec["header"]

        # Update heading hierarchy stack
        if level > 0:
            # Clear any deeper levels
            heading_stack = {lvl: h for lvl, h in heading_stack.items() if lvl < level}
            heading_stack[level] = header
            # Construct breadcrumb hierarchy (omitting H1 if it simply duplicates doc_title)
            breadcrumbs_list = [
                heading_stack[lvl] for lvl in sorted(heading_stack.keys())
                if not (lvl == 1 and heading_stack[lvl].strip().lower() == doc_title.strip().lower())
            ]
            heading_trail = " > ".join(breadcrumbs_list) if breadcrumbs_list else doc_title
        else:
            heading_trail = doc_title

        section_raw = "\n".join(sec["lines"]).strip()
        if not section_raw:
            continue

        # Check for section-level clearance override
        sec_clearance = doc_clearance
        clr_match = re.search(
            r'(?:<!--\s*clearance:\s*([a-zA-Z0-9_-]+)\s*-->|\[clearance:\s*([a-zA-Z0-9_-]+)\])',
            section_raw,
            re.IGNORECASE,
        )
        if clr_match:
            matched_val = clr_match.group(1) or clr_match.group(2)
            try:
                sec_clearance = ClearanceLevel.from_string(matched_val).value
            except Exception:
                pass

        sec_chunks = dynamic_syntactic_chunk_text(
            text=section_raw,
            min_tokens=effective_min_tokens,
            max_tokens=effective_max_tokens,
            overlap_tokens=overlap_tokens,
            default_boundary_type="header",
            doc_title=doc_title,
            filepath=filepath,
            heading=heading_trail,
            start_line=sec["start_line"],
            chunk_index_offset=chunk_counter,
            clearance_level=sec_clearance,
            tags=tags,
            aliases=aliases,
        )

        for sc in sec_chunks:
            # Check for sub-chunk specific clearance override if any
            sub_clr_match = re.search(
                r'(?:<!--\s*clearance:\s*([a-zA-Z0-9_-]+)\s*-->|\[clearance:\s*([a-zA-Z0-9_-]+)\])',
                sc.raw_content,
                re.IGNORECASE,
            )
            if sub_clr_match:
                m_val = sub_clr_match.group(1) or sub_clr_match.group(2)
                try:
                    sc.clearance_level = ClearanceLevel.from_string(m_val).value
                except Exception:
                    pass
            chunks.append(sc)
            chunk_counter += 1

    return chunks

