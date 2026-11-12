from services.inference import normalize_class

LEVELS = {
    "alta": ("Prioridade alta", 3),
    "media": ("Prioridade média", 2),
    "verificar": ("Verificar na imagem", 1),
    "sem_acionamento": ("Sem acionamento", 0),
}

CHECKLIST = [
    "Confirmar a localização (rodovia, km e sentido) com a câmera ou o usuário",
    "Confirmar o número de vítimas e se há pessoas presas nas ferragens",
    "Verificar risco na cena: fogo, vazamento, tráfego fluindo ao lado",
    "Avisar a equipe de sinalização para isolar a faixa antes da chegada",
    "Verificar o melhor acesso para a ambulância (acostamento ou faixa de apoio)",
]

DISCLAIMER = "Sugestão feita só a partir da imagem. Quem decide os recursos é a regulação médica."


def _names(rules, key):
    return {normalize_class(n) for n in rules["aph"][key]}


def make_triage(result, detections, rules):
    cfg = rules["aph"]
    dets = [d for d in detections if d["confidence"] >= cfg["min_confidence"]]
    heavy = _names(rules, "heavy_classes")
    bikes = _names(rules, "two_wheeler_classes")
    people_names = _names(rules, "people_classes")
    fire_names = _names(rules, "fire_classes")
    roll_names = _names(rules, "rollover_classes")

    vehicles = [d for d in dets if d["category"] == "vehicle"]
    people = [d for d in dets if normalize_class(d["class_name"]) in people_names]
    two_wheelers = [d for d in dets if normalize_class(d["class_name"]) in bikes]
    heavy_v = [d for d in dets if normalize_class(d["class_name"]) in heavy]
    fire = any(normalize_class(d["class_name"]) in fire_names for d in dets)
    rollover = any(normalize_class(d["class_name"]) in roll_names for d in dets)

    indicators = {
        "vehicles": len(vehicles),
        "people": len(people),
        "two_wheelers": len(two_wheelers),
        "heavy": len(heavy_v),
        "fire": fire,
        "rollover": rollover,
    }

    why = []
    if people:
        why.append(str(len(people)) + " pessoa(s) detectada(s) na imagem")
    if two_wheelers:
        why.append(str(len(two_wheelers)) + " moto(s) ou bicicleta(s) na cena")
    if heavy_v:
        why.append("veículo pesado na cena (caminhão ou ônibus)")
    if fire:
        why.append("indício de fogo")
    if rollover:
        why.append("indício de capotamento")
    if len(vehicles) >= cfg["many_vehicles"]:
        why.append(str(len(vehicles)) + " veículos na cena")

    if result == "possible":
        severe = people or two_wheelers or heavy_v or fire or rollover or len(vehicles) >= cfg["many_vehicles"]
        level = "alta" if severe else "media"
        if not why:
            why.append("possível ocorrência sem outros agravantes visíveis")
    elif result == "inconclusive":
        level = "verificar"
        why.append("o sistema não tem certeza, uma pessoa precisa olhar a imagem")
    else:
        level = "sem_acionamento"
        why.append("nenhum indício de ocorrência encontrado")

    resources = []
    if level == "alta":
        resources.append("Avaliar ambulância de suporte avançado (USA)")
        resources.append("Ambulância de suporte básico (USB) como apoio")
        if fire or rollover or heavy_v:
            resources.append("Avaliar apoio de resgate / bombeiros")
        resources.append("Equipe de sinalização e guincho")
    elif level == "media":
        resources.append("Ambulância de suporte básico (USB)")
        resources.append("Equipe de sinalização")
    elif level == "verificar":
        resources.append("Nenhum recurso até confirmar a imagem")

    return {
        "priority": level,
        "priority_label": LEVELS[level][0],
        "level": LEVELS[level][1],
        "indicators": indicators,
        "why": why,
        "resources": resources,
        "checklist": CHECKLIST if level in ("alta", "media") else [],
        "disclaimer": DISCLAIMER,
    }
