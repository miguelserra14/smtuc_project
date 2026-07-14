"""Bridge FeedNPlay.

Abre o dashboard numa janela `pywebview` sem chrome, posicionada para a parede (por omissão,
0,0,9720x1920 - a parede toda), e consome o tópico Kafka `camtop_presences` publicado pelo
produtor de câmara de topo do feednplay_devkit (ver
data_streaming/examples_of_data_producers/produce_cam_top_data_in_python/produce_cam_top_data.py
nesse repositório - câmara de topo, JSON com `presences[].centroid.{x,y}` normalizados 0-1,
`presences[].area`, pode haver 0, 1 ou várias pessoas em simultâneo).

A presença ativa (a de maior `area`, i.e. a mais próxima) é escolhida em `_presence_from_message`
e enviada para a página via `window.evaluate_js(window.__fnpOnPresence(...))` - a função JS
correspondente vive no template `feednplay_dashboard.html` e reencaminha por `postMessage` para
o iframe atualmente carregado (ver esse template e `visualizations/reachability.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import webview

try:
    import confluent_kafka
except ImportError:  # pragma: no cover - optional dependency guard
    confluent_kafka = None


DEFAULT_KAFKA_SERVER = "localhost:9092"
DEFAULT_KAFKA_TOPIC = "camtop_presences"

# Ritmo máximo a que empurramos posições novas para a página - o produtor do devkit pode
# publicar a ~30/s (uma por frame de vídeo); não há ganho nenhum em atualizar o DOM/isócrona
# mais depressa do que isto, e poupa chamadas evaluate_js (que atravessam a fronteira
# Python<->JS do pywebview) desnecessárias.
MIN_UPDATE_INTERVAL_S = 0.05


def _check_kafka_connection(server: str, topic: str, timeout_s: float = 5.0) -> bool:
    """Testa a ligação ao broker Kafka, sem consumir nenhuma mensagem ainda.

    Devolve False (nunca levanta exceção) quando o Kafka não está acessível - o esqueleto tem
    de continuar a correr sem câmara (fallback ao rato, do lado da página), não crashar. É o
    caso normal em desenvolvimento local sem o Kafka do devkit a correr.
    """
    if confluent_kafka is None:
        print("[AVISO] confluent-kafka não está instalado - a correr sem câmara.")
        return False

    consumer = confluent_kafka.Consumer(
        {
            "bootstrap.servers": server,
            "group.id": f"smtuc_feednplay_{uuid.uuid4().hex}",
        }
    )
    try:
        consumer.list_topics(topic=topic, timeout=timeout_s)
        return True
    except confluent_kafka.KafkaException as exc:
        print(f"[AVISO] Não foi possível ligar ao Kafka em {server} ({exc}) - a correr sem câmara.")
        return False
    finally:
        consumer.close()


def _presence_from_message(payload: dict) -> dict:
    """Escolhe a presença ativa de um payload `camtop_presences` (a de maior `area`, i.e. a
    mais próxima da câmara) e devolve sempre o mesmo esquema `{active, x, y, id}` - `x`/`y` a
    0-1 (esquerda/direita, perto/longe, tal como o produtor os publica), `active=False` quando
    a lista de presenças vier vazia (ninguém na zona de interação). O lado da página usa
    `active=False` para voltar a um estado "ambiente" em vez de ficar preso na última posição.
    """
    presences = payload.get("presences") or []
    if not presences:
        return {"active": False, "x": None, "y": None, "id": None}

    best = max(presences, key=lambda p: float(p.get("area", 0.0)))
    centroid = best.get("centroid") or {}
    return {
        "active": True,
        "x": float(centroid.get("x", 0.5)),
        "y": float(centroid.get("y", 0.5)),
        "id": best.get("id"),
    }


def _consume_presences_loop(consumer, window, stop_event: threading.Event) -> None:
    """Corre num thread próprio enquanto a janela estiver aberta: consome `camtop_presences`
    continuamente e envia só a presença ativa mais recente para a página.

    Processa sempre a ÚLTIMA mensagem disponível em cada ronda (a mesma estratégia do
    `FnpDataReader.java` do próprio devkit) para não acumular atraso se as mensagens chegarem
    mais depressa do que o ritmo de atualização (`MIN_UPDATE_INTERVAL_S`). Nunca deixa uma
    exceção matar o thread silenciosamente - isto tem de correr sem supervisão durante a
    apresentação, um erro pontual (mensagem malformada, falha de rede) não pode parar tudo.
    """
    last_sent_at = 0.0

    while not stop_event.is_set():
        try:
            msg = consumer.poll(timeout=0.2)
        except confluent_kafka.KafkaException as exc:
            print(f"[AVISO] Erro a consumir Kafka: {exc}")
            time.sleep(1.0)
            continue

        if msg is None or msg.error():
            continue

        # Drena mensagens adicionais já em fila, ficando só com a mais recente.
        latest = msg
        while True:
            nxt = consumer.poll(timeout=0)
            if nxt is None:
                break
            if not nxt.error():
                latest = nxt

        now = time.monotonic()
        if now - last_sent_at < MIN_UPDATE_INTERVAL_S:
            continue

        try:
            payload = json.loads(latest.value())
        except (ValueError, TypeError) as exc:
            print(f"[AVISO] Mensagem camtop_presences inválida, a ignorar: {exc}")
            continue

        presence = _presence_from_message(payload)
        last_sent_at = now

        js = f"window.__fnpOnPresence && window.__fnpOnPresence({json.dumps(presence)});"
        try:
            window.evaluate_js(js)
        except Exception as exc:  # pragma: no cover - depende de a janela ainda estar aberta
            print(f"[AVISO] Falha ao enviar posição para a página: {exc}")


def _resolve_local_url(url: str) -> str:
    """Resolve `url` para caminho absoluto quando não é já um URL com esquema (http://, etc.).

    O `pywebview` serve ficheiros locais através de um servidor HTTP interno (necessário para
    os iframes relativos que o dashboard usa - population/bgri.html, overlap/..., etc. -
    resolverem corretamente), e esse servidor não lida bem com um caminho relativo cru: fica
    dependente da pasta de onde o bridge foi corrido e pode devolver 404 mesmo com o ficheiro a
    existir (confirmado ao correr com --url "..\\outputs\\feednplay_dashboard.html" a partir de
    src/ - o pywebview só via "feednplay_dashboard.html", sem a pasta outputs/).
    """
    if "://" in url:
        return url

    path = Path(url).resolve()
    if not path.exists():
        print(f"[ERRO] Ficheiro não encontrado: {path}")
        sys.exit(1)
    return str(path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Abre o dashboard SMTUC na parede FeedNPlay")
    parser.add_argument("--url", type=str, default=None, help="Ficheiro/URL do dashboard (por omissão, outputs/feednplay_dashboard.html)")
    parser.add_argument("--title", type=str, default="SMTUC: FeedNPlay")
    parser.add_argument("--x", type=int, default=0, help="Posição x da janela (por omissão, 0 - a parede toda)")
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--w", type=int, default=9720, help="Largura da janela (por omissão, 9720 - a parede toda)")
    parser.add_argument("--h", type=int, default=1920)
    parser.add_argument("--kafka-server", type=str, default=DEFAULT_KAFKA_SERVER)
    parser.add_argument("--kafka-topic", type=str, default=DEFAULT_KAFKA_TOPIC)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    url = args.url
    if url is None:
        default_path = Path(__file__).resolve().parents[2] / "outputs" / "feednplay_dashboard.html"
        if not default_path.exists():
            print(f"[ERRO] Dashboard não encontrado em {default_path}. Corre regenerate_all_htmls.py primeiro, ou passa --url.")
            sys.exit(1)
        url = str(default_path)
    else:
        url = _resolve_local_url(url)

    has_camera = _check_kafka_connection(args.kafka_server, args.kafka_topic)
    print(f"[INFO] Sinal da câmara: {'disponível' if has_camera else 'indisponível (fallback ao rato)'}")

    window = webview.create_window(args.title, url, frameless=True, x=args.x, y=args.y, width=args.w, height=args.h)

    stop_event = threading.Event()
    consumer = None
    consumer_thread: threading.Thread | None = None

    if has_camera:
        consumer = confluent_kafka.Consumer(
            {
                "bootstrap.servers": args.kafka_server,
                "group.id": f"smtuc_feednplay_{uuid.uuid4().hex}",
                "auto.offset.reset": "latest",
            }
        )
        consumer.subscribe([args.kafka_topic])

        def _start_consumer_thread() -> None:
            # Só arranca depois da página ter carregado (evento `loaded`) - antes disso
            # `window.__fnpOnPresence` ainda não existe no lado do JS, e evaluate_js falharia.
            nonlocal consumer_thread
            consumer_thread = threading.Thread(
                target=_consume_presences_loop,
                args=(consumer, window, stop_event),
                daemon=True,
            )
            consumer_thread.start()

        window.events.loaded += _start_consumer_thread

    webview.start()

    stop_event.set()
    if consumer_thread is not None:
        consumer_thread.join(timeout=2.0)
    if consumer is not None:
        consumer.close()


if __name__ == "__main__":
    main()
