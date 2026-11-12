# ORBE — Módulo de Visão Computacional (Persona 3: Agente de Atendimento Pré-Hospitalar)

Protótipo funcional (Python · Flask · YOLO/RT-DETR · OpenCV · SQLite) que recebe uma imagem de câmera rodoviária,
executa inferência visual, aplica regras documentadas e informa se o operador deve ser notificado de uma **possível**
ocorrência. A IA apenas sugere; **a confirmação é sempre humana**.

## Executar no Visual Studio Code

```bash
# 1. dentro da pasta ORBE/ (Python 3.10–3.12 recomendado)
py -3.12 -m venv .venv            # Windows: força o Python 3.12 (3.15 ainda não tem PyTorch)
.venv\Scripts\activate            # PowerShell/CMD  |  Git Bash: source .venv/Scripts/activate  |  Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt   # use SEMPRE "python -m pip" para instalar no venv ativo (~1–2 GB)

# 2. iniciar
python app.py                     # abre em http://127.0.0.1:5000
```

Na primeira execução, se `models/modelo_visao.pt` não existir, o Ultralytics baixa o modelo genérico `yolo11s.pt`
para `models/` (**requer internet nessa única vez**; se falhar, baixe o arquivo manualmente nas *releases* do
Ultralytics e coloque-o em `models/`). Nenhuma chave de API é necessária.

Testes: `python -m pytest -q` (75 testes, não exigem GPU, internet nem o modelo).

## Foco na Persona 3 (APH)

Depois da classificação, o ORBE monta uma **triagem para o APH**: contagem de veículos, pessoas, motos/bicicletas e veículos pesados, prioridade (alta, média, verificar, sem acionamento), recursos sugeridos e checklist da cena. Ao confirmar, o operador registra o acionamento e acompanha a equipe (acionada, a caminho, no local, concluído). As sugestões são indicativas e baseadas só na imagem; a regulação médica decide os recursos.

## Dois modos de operação (importante para a apresentação)

| Modo | Quando | O que significa |
|---|---|---|
| **Genérico (COCO)** | não há `models/modelo_visao.pt` | O modelo detecta veículos/pessoas, **mas não foi treinado para acidentes**. Só há *indícios geométricos* (sobreposição forte entre veículos), sempre rotulados como tal. |
| **Acidentes** | `modelo_visao.pt` possui classes como `collision`, `vehicle_fire`… (ver `rules.json`) | Detecções de classe de acidente + corroboração → "possível ocorrência". Ativado automaticamente. |

Para obter o modo "acidentes": converter um dataset (ex.: TUMTraf-Accid3nD, conferindo a licença) para o formato YOLO,
treinar com `tools/train_detector.py` e copiar `best.pt` para `models/modelo_visao.pt`.

## Estrutura

```
app.py · config.py · rules.json · requirements.txt · .env.example
services/   aph_triage.py · image_processing.py · inference.py · occurrence_classifier.py · analysis_service.py · llm_service.py
routes/     main_routes.py · analysis_routes.py · history_routes.py
database/   db.py · models.py            (SQLite: analyses | human_decisions | definitive_occurrences)
templates/  base · dashboard · analysis · detail · history (também "revisão") · settings · error
static/     css/style.css · js/script.js · images/
tools/      evaluate.py (P/R/F1/matriz de confusão) · train_detector.py (treino e mAP)
tests/      test_inference.py · test_classifier.py · test_routes.py
docs/       RELATORIO_TECNICO.pdf/.html · diagrama_arquitetura.svg/.png
```

## Configuração

`rules.json` (limiares e classes) e `.env` (modelo, tamanho de upload, LLM opcional). Ver `.env.example`.
A integração com LLM é opcional e vem desligada; sem ela, o resumo é gerado por texto padrão.

## Avaliação

`python -m tools.evaluate --images pasta/ --labels rotulos.csv` (CSV: `arquivo,rotulo` com `ocorrencia`/`normal`).
Use somente imagens de teste, separadas do treino por cena/vídeo. Para mAP: `python tools/train_detector.py --data data.yaml --val-only`.
