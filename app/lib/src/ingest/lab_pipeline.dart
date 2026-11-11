import '../explanation/explanation_document.dart';

/// Where a row came from and how sure the extractor is about each field.
///
/// The four gates are decided by the explicit `verified` flags, never by these
/// scores: a high average must not rescue an uncertain field. The scores exist
/// so the UI can say *what* is uncertain, and the page lets a reader check the
/// row against the original report.
class ExtractionEvidence {
  const ExtractionEvidence({
    required this.page,
    this.nameConfidence = 1,
    this.valueConfidence = 1,
    this.unitConfidence = 0,
    this.referenceConfidence = 0,
    this.classificationConfidence = 1,
    this.notes = const [],
  });

  /// 1-based page number in the source PDF.
  final int page;
  final double nameConfidence;
  final double valueConfidence;
  final double unitConfidence;
  final double referenceConfidence;
  final double classificationConfidence;

  /// Human-readable review notes, in the order they should be shown.
  final List<String> notes;

  ExtractionEvidence copyWith({
    double? referenceConfidence,
    List<String>? notes,
  }) =>
      ExtractionEvidence(
        page: page,
        nameConfidence: nameConfidence,
        valueConfidence: valueConfidence,
        unitConfidence: unitConfidence,
        referenceConfidence: referenceConfidence ?? this.referenceConfidence,
        classificationConfidence: classificationConfidence,
        notes: notes ?? this.notes,
      );
}

/// A row is only "verified" when its pieces were actually found. Anything the
/// parser is unsure about stays unverified so the existing gates block it.
class ParsedLabRow {
  const ParsedLabRow({
    required this.name,
    required this.valueText,
    required this.valueKind,
    this.panel,
    this.unitText,
    this.referenceText,
    this.low,
    this.high,
    this.operator,
    this.valueVerified = false,
    this.unitVerified = false,
    this.referenceVerified = false,
    this.stratified = false,
    this.evidence,
    this.ocrDerived = false,
  });

  final String name;
  final String? panel;
  final bool stratified;
  final String valueText;
  final String valueKind; // numeric | qualitative
  final String? unitText;
  final String? referenceText;
  final double? low;
  final double? high;
  final String? operator;
  final bool valueVerified;
  final bool unitVerified;
  final bool referenceVerified;
  final ExtractionEvidence? evidence;

  /// True when the values on this row came from OCR (a scanned or partially
  /// scanned page). The safety policy keeps every OCR-derived field at
  /// `requires_review`, so all four gates are closed for such a row.
  final bool ocrDerived;

  double? get numericValue => double.tryParse(valueText);

  bool get isUsable => valueVerified && name.trim().length >= 2;

  ParsedLabRow withPanel(String? panel) => ParsedLabRow(
        name: name,
        panel: panel ?? this.panel,
        valueText: valueText,
        valueKind: valueKind,
        unitText: unitText,
        referenceText: referenceText,
        low: low,
        high: high,
        operator: operator,
        valueVerified: valueVerified,
        unitVerified: unitVerified,
        referenceVerified: referenceVerified,
        stratified: stratified,
        evidence: evidence,
        ocrDerived: ocrDerived,
      );

  /// Marks a row as OCR-derived and records why it needs review.
  ParsedLabRow withOcr() {
    final current = evidence;
    return ParsedLabRow(
      name: name,
      panel: panel,
      valueText: valueText,
      valueKind: valueKind,
      unitText: unitText,
      referenceText: referenceText,
      low: low,
      high: high,
      operator: operator,
      valueVerified: valueVerified,
      unitVerified: unitVerified,
      referenceVerified: referenceVerified,
      stratified: stratified,
      ocrDerived: true,
      evidence: current == null
          ? const ExtractionEvidence(page: 0)
          : current.copyWith(
              notes: [
                'Read with OCR from a scanned page. Values are shown as printed '
                    'but are not verified, so no comparison is made.',
                ...current.notes,
              ],
            ),
    );
  }

  ParsedLabRow withEvidence(ExtractionEvidence evidence) => ParsedLabRow(
        name: name,
        panel: panel,
        valueText: valueText,
        valueKind: valueKind,
        unitText: unitText,
        referenceText: referenceText,
        low: low,
        high: high,
        operator: operator,
        valueVerified: valueVerified,
        unitVerified: unitVerified,
        referenceVerified: referenceVerified,
        stratified: stratified,
        evidence: evidence,
        ocrDerived: ocrDerived,
      );

  ParsedLabRow withReference({
    required String text,
    double? low,
    double? high,
    String? operator,
    bool stratified = false,
    double referenceConfidence = 1,
  }) =>
      ParsedLabRow(
        name: name,
        panel: panel,
        valueText: valueText,
        valueKind: valueKind,
        unitText: unitText,
        referenceText: text,
        low: low,
        high: high,
        operator: operator,
        valueVerified: valueVerified,
        unitVerified: unitVerified,
        referenceVerified: true,
        stratified: stratified,
        ocrDerived: ocrDerived,
        evidence: evidence?.copyWith(referenceConfidence: referenceConfidence),
      );
}

class KnownTest {
  const KnownTest({required this.measures, required this.limitation, required this.sourceId});

  final String measures;
  final String limitation;
  final String sourceId;
}

const Map<String, KnownTest> knownTests = {
  'ca-125': KnownTest(
    measures: 'CA-125 is a protein that can be measured in the blood; it is used to '
        'monitor certain conditions rather than to diagnose them on its own.',
    limitation: 'CA-125 can be raised by conditions other than cancer, and a normal '
        'result does not exclude disease.',
    sourceId: 'mp_lab_cbc',
  ),
  'rheumatoid factor': KnownTest(
    measures: 'Rheumatoid factor is an antibody that can be measured in the blood.',
    limitation: 'Rheumatoid factor can be present without disease and absent with it.',
    sourceId: 'mp_lab_cmp',
  ),
  'vitamin b12': KnownTest(
    measures: 'Vitamin B12 is a vitamin needed for healthy nerves and red blood cells.',
    limitation: 'Vitamin B12 results are interpreted with diet, symptoms and other tests.',
    sourceId: 'mp_lab_cbc',
  ),
  'vitamin d': KnownTest(
    measures: 'Vitamin D is a vitamin that helps the body absorb calcium and supports '
        'bone health.',
    limitation: 'Vitamin D reference categories vary between laboratories.',
    sourceId: 'mp_lab_cmp',
  ),
  'iron': KnownTest(
    measures: 'Iron is a mineral needed to make haemoglobin in red blood cells.',
    limitation: 'Iron levels vary through the day and with recent intake.',
    sourceId: 'mp_lab_cbc',
  ),
  'tibc': KnownTest(
    measures: 'Total iron binding capacity estimates how much iron the blood can carry.',
    limitation: 'TIBC is interpreted together with iron and ferritin, not alone.',
    sourceId: 'mp_lab_cbc',
  ),
  'transferrin saturation': KnownTest(
    measures: 'Transferrin saturation describes how much of the iron-carrying capacity '
        'is in use.',
    limitation: 'It is a calculated value and inherits the uncertainty of its inputs.',
    sourceId: 'mp_lab_cbc',
  ),
  'uric acid': KnownTest(
    measures: 'Uric acid is a waste product formed when the body breaks down purines.',
    limitation: 'Uric acid can be affected by diet, hydration and medicines.',
    sourceId: 'mp_lab_cmp',
  ),
  'urea': KnownTest(
    measures: 'Urea is a waste product the kidneys remove from the blood.',
    limitation: 'Urea is interpreted with creatinine and hydration status.',
    sourceId: 'mp_lab_cmp',
  ),
  'hdl cholesterol': KnownTest(
    measures: 'HDL cholesterol helps remove other cholesterol from the blood.',
    limitation: 'Healthy levels depend on age and other risk factors.',
    sourceId: 'mp_lab_lipid',
  ),
  'ldl cholesterol': KnownTest(
    measures: 'LDL cholesterol is the main source of cholesterol build-up in arteries.',
    limitation: 'Healthy levels depend on age, family history and other risk factors.',
    sourceId: 'mp_lab_lipid',
  ),
  'triglycerides': KnownTest(
    measures: 'Triglycerides are a type of fat carried in the blood.',
    limitation: 'Triglycerides are strongly affected by recent food and alcohol intake.',
    sourceId: 'mp_lab_lipid',
  ),
  't3': KnownTest(
    measures: 'T3 is one of the thyroid hormones, which affect how the body uses energy.',
    limitation: 'T3 is interpreted with TSH and T4.',
    sourceId: 'mp_lab_tsh',
  ),
  't4': KnownTest(
    measures: 'T4 is one of the thyroid hormones, which affect how the body uses energy.',
    limitation: 'T4 is interpreted with TSH and T3.',
    sourceId: 'mp_lab_tsh',
  ),

  'hemoglobin': KnownTest(
    measures: 'Haemoglobin is the iron-rich protein in red blood cells that carries '
        'oxygen around the body.',
    limitation: 'Haemoglobin can be affected by hydration, diet, medicines and menstruation.',
    sourceId: 'mp_lab_cbc',
  ),
  'wbc': KnownTest(
    measures: 'White blood cells are part of the immune system and help the body fight '
        'infection and other diseases.',
    limitation: 'Abnormal white-cell results do not always mean a condition that needs treatment.',
    sourceId: 'mp_lab_cbc',
  ),
  'platelets': KnownTest(
    measures: 'Platelets are small cell fragments that help blood to clot.',
    limitation: 'Platelet counts can be affected by medicines and by how the sample was handled.',
    sourceId: 'mp_lab_cbc',
  ),
  'glucose': KnownTest(
    measures: 'Glucose is the body\'s main source of energy; this test measures how much '
        'is in the blood.',
    limitation: 'A single glucose reading does not by itself diagnose diabetes.',
    sourceId: 'mp_lab_cmp',
  ),
  'hba1c': KnownTest(
    measures: 'HbA1c reflects average blood glucose over the past two to three months.',
    limitation: 'Conditions affecting red blood cells can make HbA1c less reliable.',
    sourceId: 'mp_lab_hba1c',
  ),
  'creatinine': KnownTest(
    measures: 'Creatinine is a waste product that the kidneys filter out of the blood.',
    limitation: 'Creatinine is interpreted with age, muscle mass and other results.',
    sourceId: 'mp_lab_cmp',
  ),
  'cholesterol': KnownTest(
    measures: 'Cholesterol is a fat-like substance in the blood; a lipid panel measures '
        'several fractions of it.',
    limitation: 'Healthy cholesterol levels depend on age and other risk factors.',
    sourceId: 'mp_lab_lipid',
  ),
  'tsh': KnownTest(
    measures: 'TSH is a hormone from the pituitary gland that tells the thyroid how much '
        'hormone to make.',
    limitation: 'TSH can be high or low even when the thyroid is healthy.',
    sourceId: 'mp_lab_tsh',
  ),
};

const Map<String, String> _aliases = {
  'haemoglobin': 'hemoglobin',
  'hb': 'hemoglobin',
  'hgb': 'hemoglobin',
  'total leucocytes count': 'wbc',
  'total leukocyte count': 'wbc',
  'white blood cell count': 'wbc',
  'wbc count': 'wbc',
  'platelet count': 'platelets',
  'fasting blood sugar': 'glucose',
  'fasting glucose': 'glucose',
  'blood glucose': 'glucose',
  'hba1c': 'hba1c',
  'glycated hemoglobin': 'hba1c',
  's creatinine': 'creatinine',
  'serum creatinine': 'creatinine',
  'total cholesterol': 'cholesterol',
  'thyroid stimulating hormone': 'tsh',
  'b12': 'vitamin b12',
  'vit b12': 'vitamin b12',
  'vitamin b 12': 'vitamin b12',
  'vitamin b-12': 'vitamin b12',
};

String _normaliseKey(String value) =>
    value.toLowerCase().replaceAll(RegExp(r'[^a-z0-9 ]'), ' ').replaceAll(RegExp(r'\s+'), ' ').trim();

final Map<String, String> _normalisedKnown = {
  for (final key in knownTests.keys) _normaliseKey(key): key,
};
final Map<String, String> _normalisedAliases = {
  for (final entry in _aliases.entries) _normaliseKey(entry.key): entry.value,
};

KnownTest? lookupKnownTest(String name) {
  final cleaned = _normaliseKey(name);
  if (knownTests.containsKey(cleaned)) return knownTests[cleaned];
  final canonical = _normalisedKnown[cleaned];
  if (canonical != null) return knownTests[canonical];
  final alias = _aliases[cleaned] ?? _normalisedAliases[cleaned];
  if (alias != null) return knownTests[alias];
  for (final entry in knownTests.entries) {
    if (cleaned.contains(entry.key)) return entry.value;
  }
  return null;
}

final RegExp _range = RegExp(r'(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)\s*$');
final RegExp _bound = RegExp(r'([<>]=?)\s*(\d+(?:\.\d+)?)\s*$');
final RegExp _value = RegExp(r'(?<![\w.])([<>]=?)?\s*(\d+(?:\.\d+)?)(?![\w.])');
final RegExp _qualitative = RegExp(r'\b(positive|negative|absent|present|nil|trace|normal|clear|straw|pale yellow)\b', caseSensitive: false);
final RegExp _unit = RegExp(r'^[a-zA-Z%µ/^0-9.\-\s]+$');

bool _plausibleName(String name) {
  final trimmed = name.trim();
  if (trimmed.length < 3) return false;
  final lettersAndSpaces = RegExp(r'[A-Za-z ]').allMatches(trimmed).length;
  if (lettersAndSpaces / trimmed.length < 0.85) return false;
  // Allow short all-caps abbreviations (TSH, WBC, MCV, ALT) that have no vowels.
  if (RegExp(r'^[A-Z]{2,6}$').hasMatch(trimmed)) return true;
  final vowels = RegExp('[aeiouAEIOU]').allMatches(trimmed).length;
  return vowels >= 2;
}

class LabParser {
  const LabParser();

  List<ParsedLabRow> parse(String text) {
    final rows = <ParsedLabRow>[];
    String? panel;
    for (final rawLine in text.split(RegExp(r'[\r\n]+'))) {
      final line = rawLine.replaceAll(RegExp(r'\s+'), ' ').trim();
      if (_looksLikePanelHeading(line)) {
        panel = _titleCase(line);
        continue;
      }
      final row = parseLine(rawLine);
      if (row != null) rows.add(row.withPanel(panel));
    }
    return rows;
  }

  bool _looksLikePanelHeading(String line) {
    if (line.length < 6 || line.length > 60) return false;
    if (RegExp(r'[0-9]').hasMatch(line)) return false;
    if (!RegExp(r'^[A-Za-z][A-Za-z /&-]*$').hasMatch(line)) return false;
    final words = line.split(' ').where((word) => word.isNotEmpty).length;
    return words >= 2 && line == line.toUpperCase();
  }

  String _titleCase(String value) => value
      .toLowerCase()
      .split(' ')
      .map((word) => word.isEmpty ? word : '${word[0].toUpperCase()}${word.substring(1)}')
      .join(' ');

  ParsedLabRow? parseLine(String rawLine) {
    var line = rawLine.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (line.length < 8 || line.length > 140) return null;
    if (RegExp(r'^(test|result|reference|patient|report|page|lab|name|age|sex|date)', caseSensitive: false).hasMatch(line)) {
      return null;
    }

    String? referenceText;
    double? low;
    double? high;
    String? operator;
    final rangeMatch = _range.firstMatch(line);
    if (rangeMatch != null) {
      low = double.tryParse(rangeMatch.group(1)!);
      high = double.tryParse(rangeMatch.group(2)!);
      referenceText = '${rangeMatch.group(1)}-${rangeMatch.group(2)}';
      line = line.substring(0, rangeMatch.start).trim();
    } else {
      final boundMatch = _bound.firstMatch(line);
      if (boundMatch != null) {
        operator = boundMatch.group(1);
        final bound = double.tryParse(boundMatch.group(2)!);
        if (operator!.startsWith('<')) {
          high = bound;
        } else {
          low = bound;
        }
        referenceText = '${boundMatch.group(1)}${boundMatch.group(2)}';
        line = line.substring(0, boundMatch.start).trim();
      }
    }

    final valueMatch = _value.firstMatch(line);
    if (valueMatch == null) {
      final qualitative = _qualitative.firstMatch(line);
      if (qualitative == null) return null;
      final name = line.substring(0, qualitative.start).trim();
      if (name.length < 2 || !_plausibleName(name)) return null;
      return ParsedLabRow(
        name: name,
        valueText: qualitative.group(1)!,
        valueKind: 'qualitative',
        referenceText: referenceText,
        low: low,
        high: high,
        operator: operator,
        valueVerified: true,
        referenceVerified: referenceText != null,
      );
    }

    final name = line.substring(0, valueMatch.start).trim().replaceAll(RegExp(r'[:.\-]+$'), '').trim();
    if (name.length < 2 || !RegExp(r'[A-Za-z]{2}').hasMatch(name)) return null;
    if (!_plausibleName(name)) return null;

    var valueText = valueMatch.group(2)!;
    if (valueMatch.group(1) != null) valueText = '${valueMatch.group(1)}$valueText';
    final numeric = double.tryParse(valueMatch.group(2)!);
    if (numeric == null || numeric < 0 || numeric > 1000000) return null;

    final tail = line.substring(valueMatch.end).trim();
    String? unit;
    var unitVerified = false;
    if (tail.isNotEmpty && tail.length <= 24 && _unit.hasMatch(tail) && RegExp(r'[A-Za-z%µ]').hasMatch(tail)) {
      unit = tail;
      unitVerified = true;
    }

    return ParsedLabRow(
      name: name,
      valueText: valueText,
      valueKind: 'numeric',
      unitText: unit,
      referenceText: referenceText,
      low: low,
      high: high,
      operator: operator,
      valueVerified: true,
      unitVerified: unitVerified,
      referenceVerified: referenceText != null,
    );
  }
}

Map<String, bool> gatesFor(ParsedLabRow row, KnownTest? known) {
  // The safety policy in force: an OCR-derived field is never verified, however
  // confident the recogniser was. Every gate fails closed for such a row.
  final readable = !row.ocrDerived;
  final identify = known != null && readable;
  final interpret = row.valueVerified && readable;
  final unit = (row.unitVerified || row.valueKind == 'qualitative') && readable;
  final range =
      row.referenceVerified && !row.stratified && interpret && unit && readable;
  return {
    'identify_test': identify,
    'interpret_value': interpret,
    'unit_comparison': unit,
    'range_comparison': range,
  };
}

String? comparisonState(ParsedLabRow row) {
  final value = row.numericValue;
  if (row.stratified || value == null || !row.referenceVerified) return null;
  if (row.operator != null) {
    if (row.operator!.startsWith('<')) {
      final bound = row.high ?? 0;
      return value < bound ? 'satisfies_one_sided_reference' : 'violates_one_sided_reference';
    }
    final bound = row.low ?? 0;
    return value > bound ? 'satisfies_one_sided_reference' : 'violates_one_sided_reference';
  }
  if (row.low != null && value < row.low!) return 'below_range';
  if (row.high != null && value > row.high!) return 'above_range';
  return 'within_range';
}

ResultExplanation buildExplanation(ParsedLabRow row, {String resultId = 'imported'}) {
  final known = lookupKnownTest(row.name);
  final gates = gatesFor(row, known);
  final state = comparisonState(row);
  final sections = <ExplanationSection>[];
  final permitted = <String, bool>{};

  void add(ExplanationSection section) {
    sections.add(section);
    permitted[section.key] = section.permitted;
  }

  if (gates['identify_test'] == true) {
    add(ExplanationSection(
      key: 'what_this_test_measures',
      permitted: true,
      text: known!.measures,
      sources: [known.sourceId],
    ));
  } else {
    add(const ExplanationSection(
      key: 'what_this_test_measures',
      permitted: false,
      reason: 'This test is not in the app knowledge set, so MediRead does not explain it.',
    ));
  }

  final unitSuffix = row.unitText == null ? '' : ' ${row.unitText}';
  add(ExplanationSection(
    key: 'your_reported_result',
    permitted: true,
    text: 'Your report lists ${row.valueText}$unitSuffix for ${row.name}.',
  ));

  if (gates['range_comparison'] == true && state != null) {
    final reference = row.referenceText;
    final text = switch (state) {
      'within_range' => 'The reported value is inside the reference interval printed on your report ($reference$unitSuffix).',
      'below_range' => 'The reported value is below the reference interval printed on your report ($reference$unitSuffix).',
      'above_range' => 'The reported value is above the reference interval printed on your report ($reference$unitSuffix).',
      'satisfies_one_sided_reference' => 'The reported value satisfies the bound printed on your report ($reference$unitSuffix).',
      _ => 'The reported value does not satisfy the bound printed on your report ($reference$unitSuffix).',
    };
    add(ExplanationSection(key: 'comparison_with_reference', permitted: true, text: text));
  } else {
    add(const ExplanationSection(
      key: 'comparison_with_reference',
      permitted: false,
      reason: 'The unit or reference range for this row could not be verified.',
    ));
  }

  if (gates['identify_test'] == true && gates['interpret_value'] == true) {
    add(ExplanationSection(
      key: 'what_this_may_generally_indicate',
      permitted: true,
      text: 'Results like this are usually interpreted together with your symptoms, '
          'history and other test results. This is general education about the test, '
          'not a statement about your health.',
      sources: [known!.sourceId],
    ));
  } else {
    add(const ExplanationSection(
      key: 'what_this_may_generally_indicate',
      permitted: false,
      reason: 'The test or its value was not verified.',
    ));
  }

  final limitations = <String>[
    'The reference interval printed on your report is specific to the laboratory that produced it.',
    'A result outside the printed interval may or may not reflect a health problem.',
    if (known != null) known.limitation,
    'MediRead extracted this row from a PDF; values should be checked against the original report.',
    'MediRead cannot assess how urgent any result is.',
  ];
  add(ExplanationSection(
    key: 'important_limitations',
    permitted: true,
    text: limitations.join(' '),
  ));

  add(ExplanationSection(
    key: 'sources',
    permitted: known != null,
    text: known == null ? null : 'Source: MedlinePlus, National Library of Medicine.',
    reason: known == null ? 'No source is attributed for an unknown test.' : null,
    sources: known == null ? const [] : [known.sourceId],
  ));

  final explained = permitsAll(permitted, ['what_this_test_measures', 'comparison_with_reference']);
  final status = explained
      ? 'explained'
      : permitted['what_this_test_measures'] == true || permitted['comparison_with_reference'] == true
          ? 'partially_explained'
          : 'withheld';

  return ResultExplanation(
    resultId: resultId,
    testName: row.name,
    canonicalName: row.name,
    panel: row.panel,
    status: status,
    // The shipped catalogue is the approved catalogue: a known test is an
    // approved entry, an unknown one has no approved knowledge at all.
    knowledgeStatus: known == null ? 'unsupported' : 'approved',
    knowledgeCoverage: known == null ? 'unsupported' : 'complete',
    gates: gates,
    permitted: permitted,
    sections: sections,
    comparison: state == null
        ? null
        : {
            'state': state,
            'low': row.low,
            'high': row.high,
            'operator': row.operator,
          },
    facts: ResultFacts(
      valueText: row.valueText,
      unitText: row.unitText,
      referenceText: row.referenceText,
      valueKind: row.valueKind,
      comparisonState: state,
    ),
  );
}

bool permitsAll(Map<String, bool> permitted, List<String> keys) =>
    keys.every((key) => permitted[key] == true);
