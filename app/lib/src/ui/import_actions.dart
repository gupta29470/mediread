import 'package:flutter/material.dart';

import 'theme.dart';

/// The three ways into a report. Each one acts immediately — picking a PDF,
/// opening the camera or opening the gallery — instead of routing to an
/// intermediate "choose a report" screen.
class ImportActions extends StatelessWidget {
  const ImportActions({
    super.key,
    required this.enabled,
    required this.onPdf,
    required this.onCamera,
    required this.onGallery,
  });

  final bool enabled;
  final VoidCallback onPdf;
  final VoidCallback onCamera;
  final VoidCallback onGallery;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _Action(
          icon: Icons.picture_as_pdf_outlined,
          label: 'Import PDF',
          enabled: enabled,
          onTap: onPdf,
        ),
        const SizedBox(width: 10),
        _Action(
          icon: Icons.photo_camera_outlined,
          label: 'Take photo',
          enabled: enabled,
          onTap: onCamera,
        ),
        const SizedBox(width: 10),
        _Action(
          icon: Icons.photo_library_outlined,
          label: 'Gallery',
          enabled: enabled,
          onTap: onGallery,
        ),
      ],
    );
  }
}

class _Action extends StatelessWidget {
  const _Action({
    required this.icon,
    required this.label,
    required this.enabled,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Opacity(
        opacity: enabled ? 1 : 0.45,
        child: InkWell(
          onTap: enabled ? onTap : null,
          borderRadius: BorderRadius.circular(14),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 14),
            decoration: BoxDecoration(
              color: Clinical.well,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Clinical.border),
            ),
            child: Column(
              children: [
                Icon(icon, size: 22, color: Clinical.inkSecondary),
                const SizedBox(height: 6),
                Text(
                  label,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 12, color: Clinical.inkSecondary),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
