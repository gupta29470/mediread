import 'package:flutter/material.dart';

import 'src/ai/model_library.dart';
import 'src/ui/home_page.dart';
import 'src/ui/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MediReadApp());
}

class MediReadApp extends StatefulWidget {
  const MediReadApp({super.key});

  @override
  State<MediReadApp> createState() => _MediReadAppState();
}

class _MediReadAppState extends State<MediReadApp> {
  late final Future<ModelLibrary> _library;

  @override
  void initState() {
    super.initState();
    _library = buildModelLibrary();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MediRead',
      debugShowCheckedModeBanner: false,
      theme: Clinical.theme(),
      home: FutureBuilder<ModelLibrary>(
        future: _library,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Scaffold(
              body: Center(child: Text('Initialisation failed: ${snapshot.error}')),
            );
          }
          if (!snapshot.hasData) {
            return const Scaffold(body: Center(child: CircularProgressIndicator()));
          }
          return HomePage(library: snapshot.data!);
        },
      ),
    );
  }
}
