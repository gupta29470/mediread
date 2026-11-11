import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ingest/table_parser.dart';

List<Glyph> at(String text, double x, double y, {double size = 10}) {
  final glyphs = <Glyph>[];
  var cursor = x;
  for (final char in text.split('')) {
    final width = char == ' ' ? size * 0.3 : size * 0.55;
    glyphs.add(Glyph(char, cursor, y, cursor + width, y + size));
    cursor += width;
  }
  return glyphs;
}

const nameX = 40.0, techX = 220.0, valueX = 330.0, unitX = 400.0, refX = 470.0;

List<Glyph> page(List<List<String>> lines) => layout([
      for (final cells in lines)
        [
          for (var i = 0; i < cells.length; i++)
            if (cells[i].isNotEmpty) (cells[i], const [nameX, techX, valueX, unitX][i]),
        ],
    ]);

/// Body layout: one row of cells per line, cells positioned explicitly.
List<Glyph> layout(List<List<(String, double)>> lines, {double lineHeight = 18}) {
  final glyphs = <Glyph>[];
  var y = 100.0;
  for (final line in lines) {
    for (final (text, x) in line) {
      if (text.isEmpty) continue;
      glyphs.addAll(at(text, x, y));
    }
    y += lineHeight;
  }
  return glyphs;
}

/// Header with a printed reference column, as used by several real reports.
const tableHeader = <(String, double)>[
  ('TEST NAME', nameX),
  ('TECHNOLOGY', techX),
  ('VALUE', valueX),
  ('UNITS', unitX),
  ('Bio. Ref. Interval.', refX),
];

void main() {
  const parser = TableParser();

  group('separately printed reference blocks', () {
    test('reconstructs rows and binds a block printed below the row', () {
      final rows = parser.parse(page([
        ['TEST NAME', 'TECHNOLOGY', 'VALUE', 'UNITS'],
        ['CA-125', 'C.L.I.A', '29.7', 'U/mL'],
        ['Less than 30.2 U/ml'],
        ['Precision: Intra Assay (%CV): 4.3 %'],
        ['TOTAL CHOLESTEROL', 'PHOTOMETRY', '113', 'mg/dL'],
        ['<200'],
      ]));
      expect(rows.map((row) => row.name).toList(), ['Ca-125', 'Total Cholesterol']);
      expect(rows.first.valueText, '29.7');
      expect(rows.first.unitText, 'U/mL');
      expect(rows.first.referenceText, 'Less than 30.2');
      expect(rows.first.high, 30.2);
      expect(rows.last.referenceText, '<200');
      expect(rows.last.high, 200);
    });

    test('a terminated block never adopts a later table', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('CA-125', nameX), ('C.L.I.A', techX), ('29.7', valueX), ('U/mL', unitX)],
        [('Bio. Ref. Interval. :-', nameX)],
        [('Less than 30.2 U/ml', nameX)],
        [('Clinical Significance:', nameX)],
        [('3rd || 79.9-186 || 5.1-13.2 || 0.3-3.5', nameX)],
      ]));
      expect(rows.single.referenceText, 'Less than 30.2');
      expect(rows.single.high, 30.2);
      expect(rows.single.referenceText, isNot(contains('79.9')));
    });

    test('several labelled lines stay stratified instead of being flattened', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('IRON', nameX), ('PHOTOMETRY', techX), ('33', valueX), ('µg/dL', unitX)],
        [('Bio. Ref. Interval. :-', nameX)],
        [('Male : 65 - 175', nameX)],
        [('Female : 50 - 170', nameX)],
      ]));
      final row = rows.single;
      expect(row.stratified, isTrue);
      expect(row.referenceText, contains('65 - 175'));
      expect(row.referenceText, contains('Female'));
      expect(row.low, isNull);
      expect(row.high, isNull);
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isFalse);
    });

    test('a cut-off table is preserved, marked stratified and never compared', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('25-OH VITAMIN D (TOTAL)', nameX), ('C.L.I.A', techX), ('9.01', valueX), ('ng/mL', unitX)],
        [('Bio. Ref. Interval. :', nameX)],
        [('DEFICIENCY : <20 ng/ml || INSUFFICIENCY : 20-<30 ng/ml', nameX)],
        [('SUFFICIENCY : 30-100 ng/ml || TOXICITY : >100 ng/ml', nameX)],
        [('Clinical Significance:', nameX)],
      ]));
      final row = rows.single;
      expect(row.stratified, isTrue);
      expect(row.referenceText, contains('DEFICIENCY'));
      expect(row.referenceText, contains('TOXICITY'));
      expect(row.low, isNull);
      expect(row.high, isNull);
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isFalse);
    });

    test('a guidance column printed beside the block is not part of the range', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('HbA1c - (HPLC)', nameX)],
        [('4.9', valueX), ('%', unitX)],
        [('Bio. Ref. Interval. :', nameX)],
        [('Below 5.7% : Normal', nameX), ('Below 6.5% : Good Control', 300)],
        [('5.7% - 6.4% : Prediabetic', nameX), ('6.5% - 7% : Fair Control', 300)],
      ]));
      final row = rows.single;
      expect(row.name, contains('Hba1c'));
      expect(row.valueText, '4.9');
      expect(row.referenceText, contains('Prediabetic'));
      expect(row.referenceText, isNot(contains('Good Control')));
      expect(row.referenceText, isNot(contains('Fair Control')));
      expect(row.stratified, isTrue);
    });
  });

  group('printed reference column', () {
    test('reads the range from its own column and keeps the value intact', () {
      final rows = parser.parse(layout([
        tableHeader,
        [
          ('TOTAL CHOLESTEROL', nameX),
          ('PHOTOMETRY', techX),
          ('113', valueX),
          ('mg/dL', unitX),
          ('< 200', refX),
        ],
      ]));
      final row = rows.single;
      expect(row.name, 'Total Cholesterol');
      expect(row.valueText, '113');
      expect(row.unitText, 'mg/dL');
      expect(row.referenceText, '<200');
      expect(row.high, 200);
      expect(row.operator, '<');
      expect(row.stratified, isFalse);
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isTrue);
    });

    test('a stratified cell in the column is withheld, not compared', () {
      final rows = parser.parse(layout([
        tableHeader,
        [
          ('UREA (CALCULATED)', nameX),
          ('CALCULATED', techX),
          ('18.83', valueX),
          ('mg/dL', unitX),
          ('Adult : 17-43', refX),
        ],
      ]));
      final row = rows.single;
      expect(row.stratified, isTrue);
      expect(row.referenceText, contains('Adult'));
      expect(row.low, isNull);
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isFalse);
    });

    test('ratio ranges keep both sides of the colon', () {
      final rows = parser.parse(layout([
        tableHeader,
        [
          ('BUN / SR.CREATININE RATIO', nameX),
          ('CALCULATED', techX),
          ('16.3', valueX),
          ('Ratio', unitX),
          ('9:1-23:1', refX),
        ],
      ]));
      final row = rows.single;
      expect(row.low, 9);
      expect(row.high, 23);
      expect(comparisonState(row), 'within_range');
    });

    test('worded ranges and bounds parse', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('GLUCOSE', nameX), ('PHOTOMETRY', techX), ('92.9', valueX), ('mg/dL', unitX)],
        [('Bio. Ref. Interval. :-', nameX)],
        [('70 to 100', nameX)],
      ]));
      expect(rows.single.low, 70);
      expect(rows.single.high, 100);

      final bound = parser.parse(layout([
        tableHeader,
        [('GLUCOSE', nameX), ('PHOTOMETRY', techX), ('152', valueX), ('mg/dL', unitX)],
        [('Bio. Ref. Interval. :-', nameX)],
        [('126 mg/dl or higher', nameX)],
      ]));
      expect(bound.single.low, 126);
      expect(bound.single.operator, '>');
    });
  });

  group('rows', () {
    test('a name printed above its value still forms one row', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('HbA1c - (HPLC)', nameX)],
        [('4.9', valueX), ('%', unitX)],
      ]));
      final row = rows.single;
      expect(row.name, contains('Hba1c'));
      expect(row.valueText, '4.9');
      expect(row.unitText, '%');
    });

    test('a wrapped panel title does not become part of the row name', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('Complete Urinogram', nameX)],
        [('Physical Examination', nameX)],
        [('VOLUME', nameX), ('3', valueX), ('mL', unitX)],
      ]));
      expect(rows.single.name, 'Volume');
      expect(rows.single.valueText, '3');
      expect(rows.single.unitText, 'mL');
    });

    test('a parenthetical continuation is joined to the wrapped name', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('TOTAL IRON BINDING CAPACITY', nameX)],
        [('(TIBC)', nameX), ('326', valueX), ('µg/dL', unitX)],
      ]));
      expect(rows.single.name, 'Total Iron Binding Capacity (Tibc)');
      expect(rows.single.valueText, '326');
    });

    test('a printed dash is not a unit and not a reference', () {
      final rows = parser.parse(layout([
        tableHeader,
        [
          ('SPECIFIC GRAVITY', nameX),
          ('PHOTOMETRY', techX),
          ('1.02', valueX),
          ('-', unitX),
          ('-', refX),
        ],
      ]));
      final row = rows.single;
      expect(row.unitText, isNull);
      expect(row.unitVerified, isFalse);
      expect(row.referenceText, isNull);
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isFalse);
    });

    test('a multi-word qualitative result is a row', () {
      final rows = parser.parse(layout([
        tableHeader,
        [
          ('HEMOGLOBIN C', nameX),
          ('H.P.L.C', techX),
          ('Not Detected', valueX),
          ('-', unitX),
          ('--', refX),
        ],
        [
          ('HEMOGLOBIN F', nameX),
          ('H.P.L.C', techX),
          ('0.3', valueX),
          ('%', unitX),
          ('ADULT : < 2', refX),
        ],
      ]));
      expect(rows.map((row) => row.name), ['Hemoglobin C', 'Hemoglobin F']);
      expect(rows.first.valueText, 'not detected');
      expect(rows.first.valueKind, 'qualitative');
      expect(rows.first.unitText, isNull); // a printed dash is not a unit
      expect(rows.last.valueText, '0.3');
      expect(rows.last.stratified, isTrue);
    });

    test('a censored value is reported honestly and never compared', () {
      final rows = parser.parse(layout([
        tableHeader,
        [
          ('RHEUMATOID FACTOR (RF)', nameX),
          ('IMMUNOTURBIDIMETRY', techX),
          ('< 10', valueX),
          ('IU/mL', unitX),
        ],
        [('Bio. Ref. Interval. :-', nameX)],
        [('ADULT : <= 18', nameX)],
      ]));
      final row = rows.single;
      expect(row.valueText, '<10');
      expect(row.valueVerified, isFalse);
      expect(row.stratified, isTrue);
      expect(gatesFor(row, lookupKnownTest(row.name))['interpret_value'], isFalse);
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isFalse);
    });

    test('a printed reference table is never mistaken for results', () {
      final rows = parser.parse(layout([
        tableHeader,
        [
          ('DESIRABLE', nameX),
          ('<200', 140),
          ('<100', valueX),
          ('NORMAL', unitX),
          ('<150', refX),
        ],
      ]));
      expect(rows, isEmpty);
    });

    test('citations, specifications and panel headings never become rows', () {
      final rows = parser.parse(page([
        ['TEST NAME', 'TECHNOLOGY', 'VALUE', 'UNITS'],
        ['HEMOGRAM - 6 PART (DIFF)'],
        ['12 EXAMPLE STREET'],
        ['Precision: Intra Assay (%CV): 4.3 %'],
        ['Anderson SG, Bentzon MW. Bull Wld Hlth Org 1970; 42: 311-318.'],
        ['HEMOGLOBIN', 'PHOTOMETRY', '9.0', 'g/dL'],
      ]));
      expect(rows.length, 1);
      expect(rows.single.name, 'Hemoglobin');
      expect(rows.single.valueText, '9.0');
    });

    test('one-sided reference is comparable, not missing', () {
      final rows = parser.parse(page([
        ['TEST NAME', 'TECHNOLOGY', 'VALUE', 'UNITS'],
        ['TOTAL CHOLESTEROL', 'PHOTOMETRY', '113', 'mg/dL'],
        ['<200'],
      ]));
      final row = rows.single;
      expect(row.referenceText, '<200');
      expect(row.high, 200);
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isTrue);
    });
  });

  group('non-result content', () {
    // These are the false positives seen in earlier builds. Each must be
    // rejected by classification, not by matching the literal string.
    test('a panel heading with a number in its name is not a result', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('HEMOGRAM - 6 PART (DIFF)', nameX)],
        [('HEMOGLOBIN', nameX), ('PHOTOMETRY', techX), ('9.0', valueX), ('g/dL', unitX)],
      ]));
      expect(rows.map((row) => row.name), ['Hemoglobin']);
    });

    test('address fragments never become results', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('A 104 MOONLIGHT COOPERATIVE HOUSING SOCIETY', nameX)],
        [('UNITECH WEST END VIRAR WEST KARGIL NAGAR VIRAR', nameX)],
        [('12 EXAMPLE STREET', nameX)],
      ]));
      expect(rows, isEmpty);
    });

    test('a citation with a year and page range is not a result', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('CA-125', nameX), ('C.L.I.A', techX), ('29.7', valueX), ('U/mL', unitX)],
        [('Mackey SE, Creasman WT. Ovarian Cancer Screening. J. Clin Oncol 1995; 13(3); 783 - 93.', nameX)],
      ]));
      expect(rows.map((row) => row.name), ['Ca-125']);
      expect(rows.single.valueText, '29.7');
    });

    test('precision and sensitivity figures are not results', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('CEA', nameX), ('C.L.I.A', techX), ('2.1', valueX), ('ng/mL', unitX)],
        [('Precision: Intra Assay (%CV): 4.3 %, Inter Assay (%CV): 2.5%; Sensitivity: 2.0 U/ml', nameX)],
        [('Method :- TWO SITE SANDWICH IMMUNOASSAY', nameX)],
      ]));
      expect(rows.map((row) => row.name), ['Cea']);
    });

    test('standalone reference-category labels are not results', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('25-OH VITAMIN D (TOTAL)', nameX), ('C.L.I.A', techX), ('9.01', valueX), ('ng/mL', unitX)],
        [('DEFICIENCY : <20 ng/ml', nameX)],
        [('SUFFICIENCY 30', nameX)],
        [('TOXICITY : >100 ng/ml', nameX)],
      ]));
      expect(rows.map((row) => row.name), ['25-Oh Vitamin D (Total)']);
      expect(rows.single.stratified, isTrue);
    });

    test('a summary line with an availability status is not a result', () {
      final rows = parser.parse(layout([
        tableHeader,
        [('VITAMIN B-12', nameX), ('Available', valueX)],
        [('HEMOGRAM - 6 PART (DIFF)', nameX), ('Available', valueX)],
      ]));
      expect(rows, isEmpty);
    });
  });

  group('geometry', () {
    test('words follow text order even with baseline jitter', () {
      final glyphs = <Glyph>[
        ...at('TEST', 40, 100),
        ...at('NAME', 90, 100.6),
        ...at('VALUE', 300, 99.4),
      ];
      final words = buildWords(glyphs);
      expect(words.map((w) => w.text).toList(), ['TEST', 'NAME', 'VALUE']);
    });

    test('stratified references are preserved but never compared', () {
      final rows = parser.parse(page([
        ['TEST NAME', 'TECHNOLOGY', 'VALUE', 'UNITS'],
        ['IRON', 'PHOTOMETRY', '33', 'µg/dL'],
        ['Male : 65 - 175'],
      ]));
      final row = rows.single;
      expect(row.stratified, isTrue);
      expect(row.referenceText, contains('65 - 175'));
      expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isFalse);
    });
  });
}
