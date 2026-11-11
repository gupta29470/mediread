import '../explanation/explanation_document.dart';

class ValidationIssue {
  const ValidationIssue(this.code, this.detail);

  final String code;
  final String detail;

  @override
  String toString() => '$code: $detail';
}

class ValidationResult {
  const ValidationResult({this.issues = const [], this.warnings = const []});

  final List<ValidationIssue> issues;
  final List<String> warnings;

  bool get ok => issues.isEmpty;

  bool hasCode(String code) => issues.any((issue) => issue.code == code);

  static ValidationResult failure(String code, String detail) =>
      ValidationResult(issues: [ValidationIssue(code, detail)]);
}

final RegExp _numberPattern = RegExp(r'\d+(?:\.\d+)?');
final RegExp _scopeSplit = RegExp(
  r'(?:[.;!?]\s+|\bbut\b|\bhowever\b|\balthough\b)\s*',
  caseSensitive: false,
);

const List<String> _negations = [
  'not ', 'cannot', "can't", "won't", 'no ', 'never', 'without', 'unable',
  "isn't", "doesn't", "don't", "didn't", 'neither', 'nor ',
];

const List<String> _limitationMarkers = [
  'not a diagnosis',
  'not a medical diagnosis',
  'education',
  'does not replace',
  'not medical advice',
  'not a statement about your health',
];

const List<String> _permissionPhrases = [
  'within the reference range',
  'within the normal range',
  'within range',
  'in range',
  'in the normal range',
  'is normal',
  'normal result',
];

/// Interpretive assertions about the body that a rewrite may not introduce.
/// They are only acceptable if the same wording already exists in the permitted
/// explanation (then it is restatement, not a new claim).
final RegExp _bodyInference = RegExp(
  r'\b(?:means|indicates|suggests|shows)\s+(?:that\s+)?your\s+(?:blood|body|cells|levels?)\b',
  caseSensitive: false,
);
final RegExp _comparativeInference = RegExp(
  r'\b(?:contains?|have|has)\s+(?:less|more)\s+\w+\s+than\s+(?:expected|normal)\b',
  caseSensitive: false,
);

final List<MapEntry<String, RegExp>> _claimRules = [
  MapEntry('diagnosis_claim', RegExp(
    r'\byou (?:probably |likely |definitely )?have (?:a|an|the )?'
    r'(?:disease|condition|disorder|infection|cancer|diabetes|anaemia|anemia|deficiency)\b'
    r'|\b(?:this|it|the result|the finding) (?:means|indicates|confirms|shows|proves) (?:that )?you have\b'
    r'|\bdiagnosed with\b|\byou are (?:suffering|diagnosed)\b',
    caseSensitive: false,
  )),
  MapEntry('treatment_advice', RegExp(
    r'\byou should (?:start|stop|take|increase|reduce|decrease|change|avoid|try)\b'
    r'|\b(?:start|stop|take|change) (?:taking )?(?:your )?(?:medication|medicine|supplement|dose)\b'
    r'|\bincrease your dose\b|\bdecrease your dose\b|\bwe recommend\b',
    caseSensitive: false,
  )),
  MapEntry('urgency_claim', RegExp(
    r'\b(?:emergency|immediately|urgent(?:ly)?|right away|call 911|'
    r'seek (?:medical )?attention|life[- ]threatening)\b',
    caseSensitive: false,
  )),
  MapEntry('prognosis_claim', RegExp(
    r'\b(?:will develop|prognosis|life expectancy|will not survive|fatal)\b',
    caseSensitive: false,
  )),
  MapEntry('false_reassurance', RegExp(
    r'\b(?:you are (?:perfectly )?healthy|nothing to worry about|'
    r'no need to worry|perfectly normal|definitely normal|you are fine)\b',
    caseSensitive: false,
  )),
];

String _clauseBefore(String text, int index) {
  final prefix = text.substring(0, index).replaceAll('\u2019', "'").replaceAll('\u2018', "'");
  final parts = prefix.split(_scopeSplit);
  return (parts.isEmpty ? prefix : parts.last).toLowerCase();
}

bool _isNegated(String text, int index) {
  final clause = _clauseBefore(text, index);
  return _negations.any(clause.contains);
}

Set<String> numbersIn(String text) =>
    _numberPattern.allMatches(text).map((match) => match.group(0)!).toSet();

Set<String> claimCategories(String text) {
  final found = <String>{};
  for (final rule in _claimRules) {
    for (final match in rule.value.allMatches(text)) {
      if (!_isNegated(text, match.start)) {
        found.add(rule.key);
        break;
      }
    }
  }
  return found;
}

bool _assertedPermissionPhrase(String text, String phrase) {
  final pattern = RegExp(r'\b' + RegExp.escape(phrase) + r'\b', caseSensitive: false);
  for (final match in pattern.allMatches(text)) {
    final sentenceStart = text.lastIndexOf('. ', match.start) + 1;
    final sentenceEnd = text.indexOf('. ', match.start);
    final sentence = text
        .substring(sentenceStart, sentenceEnd == -1 ? text.length : sentenceEnd)
        .toLowerCase();
    if (!sentence.contains('your')) continue;
    if (sentence.contains(' if ') || sentence.contains('whether') || sentence.contains('ask ')) {
      continue;
    }
    if (_isNegated(text, match.start)) continue;
    return true;
  }
  return false;
}

String _normalise(String value) =>
    value.replaceAll(RegExp(r'\s+'), '').replaceAll('\u2013', '-').replaceAll('\u2014', '-');

Set<String> allowedNumbers(ResultExplanation result, {String extra = ''}) {
  final numbers = <String>{};
  for (final section in result.permittedSections) {
    numbers.addAll(numbersIn(section.text ?? ''));
  }
  for (final value in [
    result.facts.valueText,
    result.facts.unitText,
    result.facts.referenceText,
    result.testName,
    result.canonicalName,
    extra,
  ]) {
    if (value != null && value.isNotEmpty) numbers.addAll(numbersIn(value));
  }
  return numbers;
}

class GeneratedOutputValidator {
  const GeneratedOutputValidator();

  ValidationResult validateRewrite(
    Map<String, dynamic> output,
    ResultExplanation result,
  ) {
    final issues = <ValidationIssue>[];
    final warnings = <String>[];

    final text = output['rewritten_explanation'];
    if (text is! String || text.trim().isEmpty) {
      return ValidationResult.failure('schema', 'rewritten_explanation missing or empty');
    }
    final sources = output['used_source_ids'];
    if (sources is! List || sources.any((source) => source is! String)) {
      return ValidationResult.failure('schema', 'used_source_ids must be a list of strings');
    }
    if (output['limitations_acknowledged'] is! bool) {
      return ValidationResult.failure('schema', 'limitations_acknowledged must be a boolean');
    }
    if (output['limitations_acknowledged'] == false) {
      warnings.add('model reported limitations_acknowledged=false');
    }

    issues.addAll(_commonChecks(text, sources.cast<String>(), result,
        requirePreservation: true));
    if (!_limitationMarkers.any(text.toLowerCase().contains)) {
      issues.add(const ValidationIssue(
        'limitation_missing',
        'the rewrite dropped the educational / not-a-diagnosis statement',
      ));
    }
    return ValidationResult(issues: issues, warnings: warnings);
  }

  ValidationResult validateFollowUp(
    Map<String, dynamic> output,
    ResultExplanation result,
  ) {
    final issues = <ValidationIssue>[];
    final text = output['answer'];
    if (text is! String || text.trim().isEmpty) {
      return ValidationResult.failure('schema', 'answer missing or empty');
    }
    final sources = output['used_source_ids'];
    if (sources is! List || sources.any((source) => source is! String)) {
      return ValidationResult.failure('schema', 'used_source_ids must be a list of strings');
    }
    if (output['answerable_from_context'] is! bool) {
      return ValidationResult.failure('schema', 'answerable_from_context must be a boolean');
    }
    if (output['limitation'] is! String) {
      return ValidationResult.failure('schema', 'limitation must be a string');
    }
    issues.addAll(_commonChecks(text, sources.cast<String>(), result,
        requirePreservation: false));
    return ValidationResult(issues: issues);
  }

  List<ValidationIssue> _commonChecks(
    String text,
    List<String> citedSources,
    ResultExplanation result, {
    required bool requirePreservation,
  }) {
    final issues = <ValidationIssue>[];

    // 1. claims
    for (final category in claimCategories(text)) {
      issues.add(ValidationIssue(category, 'prohibited claim category'));
    }

    // 2. numbers must exist in permitted context
    final allowed = allowedNumbers(result);
    for (final number in numbersIn(text)) {
      if (!allowed.contains(number)) {
        issues.add(ValidationIssue('invented_number', 'number $number is not in the permitted context'));
      }
    }

    // 3. citations must be approved source ids
    final approved = result.approvedSourceIds.toSet();
    for (final source in citedSources) {
      if (!approved.contains(source)) {
        issues.add(ValidationIssue('unknown_source', 'source $source is not approved'));
      }
    }

    // 4. reported value and reference must survive a rewrite. A short follow-up
    // answer may legitimately refer to the result without repeating it.
    if (requirePreservation && result.canInterpret) {
      final value = result.facts.valueText;
      if (value != null && value.trim().isNotEmpty &&
          !_normalise(text).contains(_normalise(value))) {
        issues.add(ValidationIssue('value_omitted', 'the reported value $value is missing'));
      }
    }
    if (requirePreservation && result.canCompareRange) {
      final reference = result.facts.referenceText;
      if (reference != null && reference.trim().isNotEmpty &&
          !_normalise(text).contains(_normalise(reference))) {
        issues.add(ValidationIssue('reference_omitted', 'the reference range $reference is missing'));
      }
    }

    // 5. no newly introduced causal / physiological inference
    final contextText = result.permittedSections
        .map((section) => section.text ?? '')
        .join(' ')
        .toLowerCase();
    for (final pattern in [_bodyInference, _comparativeInference]) {
      for (final match in pattern.allMatches(text)) {
        final phrase = match.group(0)!.toLowerCase().trim();
        if (!contextText.contains(phrase)) {
          issues.add(ValidationIssue(
            'unsupported_inference',
            'adds an interpretation not present in the approved explanation: "$phrase"',
          ));
        }
      }
    }

    // 6. no range judgement when the comparison was blocked
    if (!result.canCompareRange) {
      for (final phrase in _permissionPhrases) {
        if (_assertedPermissionPhrase(text, phrase)) {
          issues.add(ValidationIssue(
            'permission_violation',
            'asserts "$phrase" although the comparison is blocked',
          ));
        }
      }
    }
    return issues;
  }
}

/// Public helper so the evaluation harness uses exactly the same assertion logic.
bool isAsserted(String text, String phrase) {
  final pattern = RegExp(r'\b' + RegExp.escape(phrase) + r'\b', caseSensitive: false);
  for (final match in pattern.allMatches(text)) {
    if (!_isNegated(text, match.start)) return true;
  }
  return false;
}
