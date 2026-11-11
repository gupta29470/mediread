import 'package:flutter/material.dart';

/// Clinical Clarity — tokens taken from the Stitch export's DESIGN.md.
class Clinical {
  static const canvas = Color(0xFFF8FAFC);
  static const surface = Color(0xFFFFFFFF);
  static const primary = Color(0xFF0D9488);
  static const primaryDark = Color(0xFF0F766E);
  static const tealWash = Color(0xFFF0FDFA);
  static const tealBorder = Color(0xFFCCFBF1);
  static const ink = Color(0xFF0F172A);
  static const inkSecondary = Color(0xFF334155);
  static const muted = Color(0xFF64748B);
  static const border = Color(0xFFE2E8F0);
  static const well = Color(0xFFF1F5F9);

  static const normalBg = Color(0xFFECFDF5);
  static const normalFg = Color(0xFF047857);
  static const alertBg = Color(0xFFFFFBEB);
  static const alertFg = Color(0xFFB45309);
  static const criticalBg = Color(0xFFFFF1F2);
  static const criticalFg = Color(0xFFBE123C);
  static const infoBg = Color(0xFFEEF2FF);
  static const infoFg = Color(0xFF4338CA);

  static ThemeData theme() {
    final base = ThemeData(useMaterial3: true, colorSchemeSeed: primary);
    return base.copyWith(
      scaffoldBackgroundColor: canvas,
      colorScheme: base.colorScheme.copyWith(
        primary: primary,
        surface: surface,
        error: criticalFg,
      ),
      textTheme: base.textTheme.apply(
        bodyColor: ink,
        displayColor: ink,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: canvas,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
        foregroundColor: ink,
        titleTextStyle: TextStyle(
          color: ink,
          fontSize: 20,
          fontWeight: FontWeight.w700,
          letterSpacing: -0.2,
        ),
      ),
      dividerTheme: const DividerThemeData(color: border, thickness: 1, space: 1),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: primary,
          foregroundColor: Colors.white,
          minimumSize: const Size.fromHeight(48),
          shape: const StadiumBorder(),
          textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: primary,
          backgroundColor: tealWash,
          side: const BorderSide(color: tealBorder),
          shape: const StadiumBorder(),
        ),
      ),
    );
  }

  static BoxDecoration card({Color? color, double radius = 16}) => BoxDecoration(
        color: color ?? surface,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: border),
        boxShadow: const [
          BoxShadow(color: Color(0x0A0F172A), blurRadius: 3, offset: Offset(0, 1)),
          BoxShadow(color: Color(0x080F172A), blurRadius: 16, offset: Offset(0, 6)),
        ],
      );
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, required this.bg, required this.fg, this.dot = true});

  final String label;
  final Color bg;
  final Color fg;
  final bool dot;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (dot) ...[
            Container(width: 6, height: 6, decoration: BoxDecoration(color: fg, shape: BoxShape.circle)),
            const SizedBox(width: 6),
          ],
          Text(label,
              style: TextStyle(color: fg, fontSize: 11, fontWeight: FontWeight.w600, letterSpacing: 0.2)),
        ],
      ),
    );
  }
}

class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(text,
            style: const TextStyle(
                color: Clinical.ink, fontSize: 18, fontWeight: FontWeight.w600, letterSpacing: -0.1)),
        const Spacer(),
        ?trailing,
      ],
    );
  }
}
