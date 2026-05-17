from pathlib import Path
import sys
sys.path.insert(0, str(Path('src').resolve()))

from visualizations import generate_connection_visualizations

# Regenerate Portela integration (Portagem -> Portela)
print("Gerando integração Portela...")
result_portela = generate_connection_visualizations(
    metro_stop_ref="Portela",
    bus_stop_ref="Portela do Mondego",
    line_number="54",
    metro_origin_ref="Portagem",
    bus_origin_ref="Portagem",
    output_prefix="line_54",
    output_subdir="portela",
    fixed_html_name="l54_all.html"
)
print(f"✓ Portela: {result_portela.get('combined_html', 'N/A')}")

# Regenerate Portagem integration (Portela -> Portagem)
print("Gerando integração Portagem...")
result_portagem = generate_connection_visualizations(
    metro_stop_ref="Portagem",
    bus_stop_ref="Portagem",
    line_number="54",
    metro_origin_ref="Portela",
    bus_origin_ref="Portela do Mondego",
    output_prefix="line_54",
    output_subdir="portagem",
    fixed_html_name="l54_portagem_all.html"
)
print(f"✓ Portagem: {result_portagem.get('combined_html', 'N/A')}")

print("\n✓ Ficheiros regenerados com a template atualizada!")
