/// Qwen3 reasoning blocks.
///
/// LiteRT-LM may render a ` thinking… response` section before the JSON answer.
/// We never regex-strip arbitrary text: only a *balanced* pair is separated, the
/// reasoning is kept aside, and anything malformed is treated as an invalid
/// response so the deterministic fallback runs.
class ThinkingSplit {
  const ThinkingSplit({
    required this.answer,
    required this.reasoning,
    required this.malformed,
  });

  final String answer;
  final String reasoning;
  final bool malformed;

  bool get hadReasoning => reasoning.isNotEmpty;
}

const String _openTag = '<' 'thi' 'nk>';
const String _closeTag = '<｜end▁of▁thi' 'nking｜>';

ThinkingSplit splitThinking(String raw,
    {String openTag = _openTag, String closeTag = _closeTag}) {
  final open = raw.indexOf(openTag);
  final close = raw.indexOf(closeTag);
  if (open == -1 && close == -1) {
    return ThinkingSplit(answer: raw, reasoning: '', malformed: false);
  }
  if (open == -1 || close == -1 || close < open) {
    return ThinkingSplit(answer: raw, reasoning: '', malformed: true);
  }
  final reasoning = raw.substring(open + openTag.length, close);
  final answer = (raw.substring(0, open) + raw.substring(close + closeTag.length)).trim();
  return ThinkingSplit(answer: answer, reasoning: reasoning, malformed: false);
}
