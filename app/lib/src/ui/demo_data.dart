import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;

import '../explanation/explanation_document.dart';

class DemoCase {
  const DemoCase({required this.caseId, required this.scenario, required this.task});

  final String caseId;
  final String scenario;
  final String task;
}

class DemoData {
  static Future<Map<String, ResultExplanation>> loadExplanations() async {
    final raw = await rootBundle.loadString('assets/demo/explanations.json');
    final decoded = jsonDecode(raw) as Map<String, dynamic>;
    return decoded.map(
      (key, value) => MapEntry(
        key,
        ResultExplanation.fromJson(value as Map<String, dynamic>),
      ),
    );
  }

  static Future<Map<String, String>> loadCannedOutputs() async {
    final raw = await rootBundle.loadString('assets/eval/canned_e4b.json');
    final decoded = jsonDecode(raw) as Map<String, dynamic>;
    return decoded.map((key, value) => MapEntry(key, value.toString()));
  }

  static Future<List<DemoCase>> loadCases() async {
    final raw = await rootBundle.loadString('assets/eval/cases.json');
    final decoded = jsonDecode(raw) as Map<String, dynamic>;
    return (decoded['cases'] as List<dynamic>).map((entry) {
      final json = entry as Map<String, dynamic>;
      return DemoCase(
        caseId: json['case_id'] as String,
        scenario: json['scenario'] as String,
        task: json['task'] as String,
      );
    }).toList(growable: false);
  }
}
