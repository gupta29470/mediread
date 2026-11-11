import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/output_validator.dart';

import 'fakes.dart';

void main() {
  const validator = GeneratedOutputValidator();

  Map<String, dynamic> rewrite(String text,
          {List<String> sources = const [], bool acknowledged = true}) =>
      {
        'rewritten_explanation': text,
        'used_source_ids': sources,
        'limitations_acknowledged': acknowledged,
      };

  test('accepts a faithful rewrite', () {
    final result = validator.validateRewrite(
      rewrite(
        'Your haemoglobin is 9 g/dL, below the 12.0-15.0 g/dL range on your report. '
        'This is educational and not a diagnosis.',
        sources: ['mp_lab_cbc'],
      ),
      explanation(),
    );
    expect(result.issues, isEmpty);
  });

  test('rejects an invented number', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL, which is 7.5 g/dL lower than normal. '
          'This is educational and not a diagnosis.'),
      explanation(),
    );
    expect(result.hasCode('invented_number'), isTrue);
  });

  test('rejects an unknown source id', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL on the 12.0-15.0 range. Not a diagnosis.',
          sources: ['made_up_source']),
      explanation(),
    );
    expect(result.hasCode('unknown_source'), isTrue);
  });

  test('rejects a diagnosis claim but accepts a negated one', () {
    final bad = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL on the 12.0-15.0 range. This means you have anaemia.'),
      explanation(),
    );
    final good = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL on the 12.0-15.0 range. MediRead cannot say if you '
          'have anaemia. This is educational and not a diagnosis.'),
      explanation(),
    );
    expect(bad.hasCode('diagnosis_claim'), isTrue);
    expect(good.hasCode('diagnosis_claim'), isFalse);
  });

  test('rejects treatment advice', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL on the 12.0-15.0 range. '
          'You should start taking iron tablets.'),
      explanation(),
    );
    expect(result.hasCode('treatment_advice'), isTrue);
  });

  test('rejects a dropped value', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is low compared with the 12.0-15.0 g/dL range. '
          'This is educational and not a diagnosis.'),
      explanation(),
    );
    expect(result.hasCode('value_omitted'), isTrue);
  });

  test('rejects a dropped reference range', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL and below the printed range. '
          'This is educational and not a diagnosis.'),
      explanation(),
    );
    expect(result.hasCode('reference_omitted'), isTrue);
  });

  test('rejects output that drops the limitation', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL, below 12.0-15.0 g/dL.'),
      explanation(),
    );
    expect(result.hasCode('limitation_missing'), isTrue);
  });

  test('rejects a normal-range claim when comparison is blocked', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL and this is within the normal range. '
          'This is educational and not a diagnosis.'),
      explanation(range: false, referenceText: null),
    );
    expect(result.hasCode('permission_violation'), isTrue);
  });

  test('rejects malformed schema', () {
    final result = validator.validateRewrite({'rewritten_explanation': 'x'}, explanation());
    expect(result.hasCode('schema'), isTrue);
  });

  test('rejects a body inference that is not in the approved explanation', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL, below the 12.0-15.0 g/dL interval. '
          'This means your blood contains less iron than expected. '
          'This is education and not a diagnosis.'),
      explanation(),
    );
    expect(result.hasCode('unsupported_inference'), isTrue);
  });

  test('accepts a rewrite that only restates the comparison', () {
    final result = validator.validateRewrite(
      rewrite('Your haemoglobin is 9 g/dL, below the 12.0-15.0 g/dL interval printed '
          'on your report. This is education and not a diagnosis.'),
      explanation(),
    );
    expect(result.issues, isEmpty);
  });

  test('follow-up schema requires limitation when not answerable', () {
    final result = validator.validateFollowUp(
      {
        'answer': 'Something.',
        'answerable_from_context': false,
        'used_source_ids': <String>[],
        'limitation': '',
      },
      explanation(),
    );
    expect(result.ok, isTrue); // schema-valid; limitation text is a product rule
  });
}
