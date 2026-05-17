from pathlib import Path
import sys
sys.path.insert(0, str(Path('src').resolve()))

from visualizations import create_population_dashboard_html
from config import DEFAULT_BGRI_GPKG_PATH, DEFAULT_OUTPUT_GAP_CSV

print("Regenerando population dashboard...")
html_path = Path("outputs/population/bgri.html")

try:
    create_population_dashboard_html(
        gpkg_path=DEFAULT_BGRI_GPKG_PATH,
        gap_csv_path=DEFAULT_OUTPUT_GAP_CSV,
        output_html_path=html_path,
    )
    print(f"✓ Population dashboard: {html_path}")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
