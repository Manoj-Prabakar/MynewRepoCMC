"""
Optimized main runner for TTS -> STT processing.

Flow:
1. Load config from BOT-TO-TEST-CONFIGURATION-INFO.txt
2. Read utterances from input Excel
3. Generate temporary MP3s via selected TTS backend
4. Run immediate STT on each MP3
5. Append results to CSV during runtime
6. Delete MP3 immediately after STT
7. Export final Excel once at the end
"""

import argparse
import json
import sys
from pathlib import Path

from updated_tts_generator import generate_audio_files


if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


def parse_config_value(raw_value: str):
    value = raw_value.strip()
    if not value:
        return ''

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    lowered = value.lower()
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False

    try:
        return int(value)
    except ValueError:
        return value


def load_config(config_file: str):
    config_path = Path(config_file)
    if not config_path.exists():
        raise FileNotFoundError(f'Configuration file not found: {config_path}')

    config = {}
    with open(config_path, 'r', encoding='utf-8') as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key, value = stripped.split('=', 1)
            config[key.strip()] = parse_config_value(value)
    return config


def main():
    parser = argparse.ArgumentParser(
        description='Optimized TTS -> STT pipeline with immediate audio cleanup',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python updated_main.py sample-utterance.xlsx
  python updated_main.py sample-utterance.xlsx --limit 5 --batch-size 4
        """,
    )

    parser.add_argument('excel_file', help='Path to Excel file with an Utterance column')
    parser.add_argument('--config-file', default='BOT-TO-TEST-CONFIGURATION-INFO.txt', help='Path to config file')
    parser.add_argument('--output-dir', default='test-output', help='Output directory for CSV/Excel results')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of utterances to process')
    parser.add_argument('--stt-model', default='tiny', help='Whisper model to use for STT (tiny, base, small, ...)')
    parser.add_argument('--batch-size', type=int, default=4, help='Parallel TTS/STT workers per utterance')

    args = parser.parse_args()

    excel_path = Path(args.excel_file)
    if not excel_path.exists():
        print(f'❌ Error: Excel file not found: {excel_path}')
        return 1

    try:
        config = load_config(args.config_file)
    except Exception as exc:
        print(f'❌ Error loading configuration: {exc}')
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tts_service = str(config.get('TTS_SERVICE', 'google')).lower()
    if tts_service not in {'edge', 'google', 'azure'}:
        print(f"[WARNING] Invalid TTS_SERVICE '{tts_service}'. Falling back to 'google'.")
        tts_service = 'google'

    creds_path = config.get('CREDS_PATH') if tts_service == 'google' else None
    azure_key = config.get('AZURE_SPEECH_KEY') if tts_service == 'azure' else None
    azure_region = config.get('AZURE_SPEECH_REGION') if tts_service == 'azure' else None

    print('=' * 70)
    print('OPTIMIZED TTS -> STT PIPELINE')
    print('=' * 70)
    print(f'Excel file    : {excel_path.resolve()}')
    print(f'Config file   : {Path(args.config_file).resolve()}')
    print(f'Output dir    : {output_dir.resolve()}')
    print(f'TTS service   : {tts_service.upper()}')
    print(f'STT model     : {args.stt_model}')
    print(f'Batch size    : {args.batch_size}')
    print(f'Limit         : {args.limit if args.limit else "ALL"}')
    print('=' * 70)

    try:
        results = generate_audio_files(
            excel_path=excel_path,
            output_dir=output_dir,
            limit=args.limit,
            tts_service=tts_service,
            creds_path=creds_path,
            azure_key=azure_key,
            azure_region=azure_region,
            stt_model_name=args.stt_model,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        print(f'\n❌ Pipeline failed: {exc}')
        import traceback
        traceback.print_exc()
        return 1

    results_file = output_dir / 'tts_stt_results.json'
    with open(results_file, 'w', encoding='utf-8') as file:
        json.dump(results, file, indent=2)

    print('\n' + '=' * 70)
    print('PIPELINE COMPLETED SUCCESSFULLY')
    print('=' * 70)
    print(f"Processed utterances : {results.get('utterances_processed', 0)}")
    print(f"Successful outputs   : {results.get('total_files', 0)} / {results.get('total_expected', 0)}")
    print(f"CSV results          : {results.get('csv_output', '')}")
    print(f"Excel results        : {results.get('excel_output', '')}")
    print(f"JSON summary         : {results_file}")
    print('=' * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
