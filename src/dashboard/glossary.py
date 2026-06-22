"""Plain-language glossary for the consolidated income statement (conto economico).

The descriptions explain, for non-experts, what each line item of the conto
economico actually represents. The wording is grounded in the official source
that defines the harmonised statement schema and its line items:

  * D.Lgs 23 giugno 2011, n. 118 -- Allegato 4/3, "Principio contabile applicato
    concernente la contabilita' economico-patrimoniale" (defines every voce of
    the conto economico);
  * D.Lgs 118/2011 -- Allegato 10, schema di conto economico (the A/B/C/D/E
    structure and the totals/subtotals).

Both are published by the Ragioneria Generale dello Stato (ARCONET).

Coverage focuses on the voci that weigh at least ~200 mln EUR in the Comune di
Torino consolidated income statement, but entries are matched by voce name, so
they apply across every year in which the voce appears.
"""

from __future__ import annotations

# Authoritative references, cited in each tooltip.
SRC_PRINCIPIO = "Allegato 4/3 al D.Lgs 118/2011 (principio contab. economico-patrimoniale, RGS-ARCONET)"
SRC_SCHEMA = "Schema di conto economico, Allegato 10 al D.Lgs 118/2011 (RGS-ARCONET)"
SRC_CONSOLIDATO = "Allegato 4/4 al D.Lgs 118/2011 (principio contab. del bilancio consolidato, RGS-ARCONET)"

# Each entry: a normalised name prefix -> (description, source).
# Matching is longest-prefix-first on the lower-cased, space-collapsed voce name,
# so e.g. "personale" matches the voce "Personale" but the more specific
# "ammortamenti di immobilizzazioni materiali" wins over "ammortamenti e ...".
_GLOSSARY: dict[str, tuple[str, str]] = {
    "proventi da tributi": (
        "Entrate di natura tributaria di competenza dell'esercizio: imposte, tasse, "
        "addizionali e compartecipazioni (ad es. IMU, TARI, addizionale IRPEF). "
        "Sono iscritte al lordo degli aggi versati al concessionario della riscossione.",
        SRC_PRINCIPIO,
    ),
    "proventi da trasferimenti e contributi": (
        "Contributi e trasferimenti ricevuti dall'ente. E' la somma di: trasferimenti "
        "correnti (a), quota annuale di contributi agli investimenti (b) e contributi "
        "agli investimenti (c).",
        SRC_SCHEMA,
    ),
    "proventi da trasferimenti correnti": (
        "Trasferimenti correnti ricevuti da Stato, Regione, Unione Europea, altre "
        "amministrazioni pubbliche e altri soggetti per finanziare la spesa corrente.",
        SRC_PRINCIPIO,
    ),
    "ricavi delle vendite e prestazioni e proventi da servizi pubblici": (
        "Proventi derivanti dall'erogazione dei servizi pubblici (istituzionali, a "
        "domanda individuale o produttivi) e dalla vendita di beni e prestazioni. E' "
        "tipicamente la voce piu' rilevante, per via delle societa' partecipate del "
        "Gruppo (es. Iren, GTT, SMAT).",
        SRC_PRINCIPIO,
    ),
    "ricavi e proventi dalla prestazione di servizi": (
        "Quota dei ricavi della voce precedente che deriva specificamente dalla "
        "prestazione di servizi a terzi.",
        SRC_PRINCIPIO,
    ),
    "altri ricavi e proventi diversi": (
        "Proventi di competenza dell'esercizio non riconducibili alle altre voci e "
        "privi di carattere straordinario.",
        SRC_PRINCIPIO,
    ),
    "totale componenti positivi della gestione": (
        "Totale dei ricavi e proventi della gestione operativa (sezione A): la somma "
        "delle voci 1-9. Rappresenta il valore della produzione del Gruppo.",
        SRC_SCHEMA,
    ),
    "acquisto di materie prime": (
        "Costi per l'acquisto di materie prime, merci e beni di consumo necessari "
        "all'attivita' ordinaria dell'ente e del Gruppo.",
        SRC_PRINCIPIO,
    ),
    "prestazioni di servizi": (
        "Costi per servizi acquisiti da terzi e connessi alla gestione operativa: "
        "utenze, manutenzioni, appalti, consulenze, aggi di riscossione, ecc.",
        SRC_PRINCIPIO,
    ),
    "personale": (
        "Costo del personale dipendente di competenza dell'esercizio: retribuzioni, "
        "straordinari, indennita' e oneri previdenziali e assistenziali.",
        SRC_PRINCIPIO,
    ),
    "ammortamenti di immobilizzazioni materiali": (
        "Quota annua di ammortamento dei beni materiali (fabbricati, impianti, "
        "infrastrutture, macchinari), che ripartisce il loro costo sulla vita utile.",
        SRC_PRINCIPIO,
    ),
    "ammortamenti e svalutazioni": (
        "Quote di ammortamento delle immobilizzazioni materiali e immateriali e "
        "svalutazioni dei crediti e delle altre attivita'.",
        SRC_PRINCIPIO,
    ),
    "totale componenti negativi della gestione": (
        "Totale dei costi e oneri della gestione operativa (sezione B): la somma "
        "delle voci 9-18.",
        SRC_SCHEMA,
    ),
    "differenza fra comp": (
        "Risultato della gestione operativa: componenti positivi (A) meno componenti "
        "negativi (B). E' l'avanzo o il disavanzo della gestione caratteristica, prima "
        "delle componenti finanziarie e straordinarie.",
        SRC_SCHEMA,
    ),
    "risultato prima delle imposte": (
        "Risultato economico prima delle imposte: (A-B) corretto dalla gestione "
        "finanziaria (C), dalle rettifiche di valore delle attivita' finanziarie (D) "
        "e dalla gestione straordinaria (E).",
        SRC_SCHEMA,
    ),
    # -- ulteriori voci >= 100 mln EUR -----------------------------------------
    "proventi da fondi perequativi": (
        "Proventi di natura tributaria derivanti dai fondi perequativi (risorse "
        "redistribuite dallo Stato per ridurre gli squilibri di gettito tra enti), "
        "di competenza dell'esercizio.",
        SRC_PRINCIPIO,
    ),
    "proventi derivanti dalla gestione dei beni": (
        "Ricavi legati alla gestione dei beni iscritti tra le immobilizzazioni dello "
        "stato patrimoniale, quali locazioni e concessioni.",
        SRC_PRINCIPIO,
    ),
    "trasferimenti e contributi": (
        "Oneri per trasferimenti correnti e contributi agli investimenti erogati "
        "dall'ente ad altre amministrazioni pubbliche o a privati senza "
        "controprestazione (lato costi della gestione).",
        SRC_PRINCIPIO,
    ),
    "trasferimenti correnti": (
        "Oneri per le risorse correnti trasferite dall'ente ad altre amministrazioni "
        "pubbliche o a privati senza controprestazione.",
        SRC_PRINCIPIO,
    ),
    "ammortamenti di immobilizzazioni immateriali": (
        "Quota annua di ammortamento dei beni immateriali (es. software, diritti, "
        "oneri pluriennali), che ne ripartisce il costo sulla vita utile.",
        SRC_PRINCIPIO,
    ),
    "svalutazione dei crediti": (
        "Accantonamento che riduce il valore dei crediti di funzionamento per la "
        "quota stimata di difficile esigibilita'.",
        SRC_PRINCIPIO,
    ),
    "interessi ed altri oneri finanziari": (
        "Oneri della gestione finanziaria di competenza dell'esercizio: interessi su "
        "mutui, prestiti, obbligazioni e anticipazioni, e altri oneri finanziari.",
        SRC_PRINCIPIO,
    ),
    "interessi passivi": (
        "Interessi a carico dell'ente sui debiti finanziari (mutui, prestiti "
        "obbligazionari, anticipazioni).",
        SRC_PRINCIPIO,
    ),
    "proventi straordinari": (
        "Proventi non ricorrenti della gestione straordinaria (sezione E): "
        "sopravvenienze attive, plusvalenze patrimoniali e altri proventi straordinari.",
        SRC_PRINCIPIO,
    ),
    "sopravvenienze attive e insussistenze del passivo": (
        "Proventi di competenza di esercizi precedenti derivanti da incrementi "
        "definitivi del valore di attivita' o dal venir meno di passivita'.",
        SRC_PRINCIPIO,
    ),
    "oneri straordinari": (
        "Oneri non ricorrenti della gestione straordinaria (sezione E): "
        "sopravvenienze passive, minusvalenze patrimoniali e altri oneri straordinari.",
        SRC_PRINCIPIO,
    ),
    "sopravvenienze passive e insussistenze dell'attivo": (
        "Oneri di competenza di esercizi precedenti derivanti da incrementi "
        "definitivi del valore di passivita' o dal venir meno di attivita'.",
        SRC_PRINCIPIO,
    ),
    "totale proventi finanziari": (
        "Totale dei proventi della gestione finanziaria (sezione C): interessi attivi "
        "e altri proventi finanziari.",
        SRC_SCHEMA,
    ),
    "totale oneri finanziari": (
        "Totale degli oneri della gestione finanziaria (sezione C): interessi passivi "
        "e altri oneri finanziari.",
        SRC_SCHEMA,
    ),
    "totale (c)": (
        "Saldo della gestione finanziaria (sezione C): proventi finanziari meno oneri "
        "finanziari.",
        SRC_SCHEMA,
    ),
    "totale proventi": (
        "Totale dei proventi della gestione straordinaria (sezione E).",
        SRC_SCHEMA,
    ),
    "totale oneri": (
        "Totale degli oneri della gestione straordinaria (sezione E).",
        SRC_SCHEMA,
    ),
    "risultato dell'esercizio di gruppo": (
        "Quota del risultato d'esercizio di competenza della capogruppo (Comune di "
        "Torino), al netto della quota attribuita ai soci di minoranza (terzi).",
        SRC_CONSOLIDATO,
    ),
    "risultato dell'esercizio": (
        "Risultato economico finale: differenza tra il totale dei proventi/ricavi e "
        "il totale degli oneri/costi dell'esercizio. Nel consolidato e' comprensivo "
        "della quota di pertinenza di terzi.",
        SRC_PRINCIPIO,
    ),
}

# Longest keys first so the most specific description wins.
_KEYS = sorted(_GLOSSARY, key=len, reverse=True)


def _normalize(name) -> str:
    if name is None or (isinstance(name, float) and name != name):
        return ""
    return " ".join(str(name).lower().split())


def lookup(name) -> tuple[str, str] | None:
    """Return ``(description, source)`` for an income-statement voce, or None.

    Matching is by normalised name prefix, longest match first.
    """
    norm = _normalize(name)
    if not norm:
        return None
    for key in _KEYS:
        if norm.startswith(key):
            return _GLOSSARY[key]
    return None


# --- Rendiconto della gestione: missioni di spesa e titoli di entrata --------
# Plain-language descriptions of the harmonised spending *missioni* and revenue
# *titoli*, grounded in the official glossary that defines them:
SRC_MISSIONI = "Allegato 14 al D.Lgs 118/2011 - Glossario delle missioni e dei programmi (RGS-ARCONET)"
SRC_TITOLI = "Schema di bilancio armonizzato, Allegato 9 al D.Lgs 118/2011 (RGS-ARCONET)"

# Keyed by missione code ('01'..'99').
MISSIONI: dict[str, str] = {
    "01": "Amministrazione e funzionamento dei servizi generali dell'ente: organi "
          "istituzionali, gestione amministrativa, finanziaria e del personale, tributi, "
          "anagrafe e servizi demografici, ufficio tecnico.",
    "02": "Attivita' di supporto al funzionamento degli uffici giudiziari di competenza "
          "comunale (es. spese per sedi e servizi connessi).",
    "03": "Polizia locale e amministrativa, sicurezza urbana, controllo del territorio e "
          "attivita' connesse all'ordine pubblico.",
    "04": "Servizi per l'istruzione (scuole dell'infanzia, primaria e secondaria), edilizia "
          "scolastica, diritto allo studio, refezione e trasporto scolastico.",
    "05": "Tutela e valorizzazione del patrimonio culturale: musei, biblioteche, teatri, "
          "archivi ed eventi e attivita' culturali.",
    "06": "Impianti e attivita' sportive, promozione dello sport, politiche per i giovani e "
          "attivita' ricreative e del tempo libero.",
    "07": "Promozione e sviluppo turistico del territorio.",
    "08": "Urbanistica e pianificazione del territorio, edilizia residenziale pubblica e "
          "politiche per la casa.",
    "09": "Gestione dei rifiuti, servizio idrico integrato, tutela dell'ambiente, verde "
          "pubblico e difesa del suolo.",
    "10": "Trasporto pubblico locale, viabilita', infrastrutture stradali e mobilita'.",
    "11": "Protezione civile: prevenzione, previsione e gestione delle emergenze.",
    "12": "Servizi sociali e politiche per la famiglia: assistenza a minori, anziani, "
          "disabili e fasce deboli, contrasto alla poverta', servizi cimiteriali.",
    "13": "Servizi sanitari di competenza comunale (per i Comuni quasi assenti: la sanita' "
          "e' competenza regionale).",
    "14": "Sostegno alle attivita' produttive: commercio, industria, artigianato, ricerca e "
          "innovazione.",
    "15": "Servizi per il lavoro, formazione professionale e sostegno all'occupazione.",
    "16": "Agricoltura, politiche agroalimentari e pesca.",
    "17": "Reti e servizi di pubblica utilita' nel settore energetico: efficienza e fonti "
          "rinnovabili.",
    "18": "Relazioni con le altre autonomie territoriali e locali (trasferimenti e rapporti "
          "finanziari tra enti).",
    "19": "Cooperazione e relazioni internazionali dell'ente.",
    "20": "Fondi e accantonamenti: fondo di riserva, fondo crediti di dubbia esigibilita' "
          "(FCDE) e altri accantonamenti. NON e' spesa erogata, ma somme accantonate per "
          "prudenza e quindi tipicamente non pagate.",
    "50": "Debito pubblico: rimborso delle quote capitale e degli interessi sui mutui e "
          "prestiti dell'ente.",
    "60": "Anticipazioni finanziarie: anticipazioni di cassa dall'istituto tesoriere e loro "
          "restituzione (partite di importo molto variabile, non spesa effettiva).",
    "99": "Servizi per conto terzi e partite di giro (es. ritenute, depositi): entrate e "
          "spese di pari importo che NON costituiscono spesa effettiva dell'ente.",
}

# Keyed by titolo code ('1'..'9').
TITOLI: dict[str, str] = {
    "1": "Tributi propri dell'ente (es. IMU, TARI, addizionale IRPEF), compartecipazioni a "
         "tributi erariali e fondi perequativi.",
    "2": "Contributi e trasferimenti correnti ricevuti da Stato, Regione, Unione Europea e "
         "altri enti per finanziare la spesa corrente.",
    "3": "Entrate extratributarie: proventi dei servizi pubblici, vendita di beni, sanzioni, "
         "redditi da capitale, fitti e canoni.",
    "4": "Entrate in conto capitale: contributi agli investimenti, alienazioni di beni e "
         "proventi dei permessi di costruire.",
    "5": "Entrate da riduzione di attivita' finanziarie: riscossione di crediti, alienazione "
         "di partecipazioni e altre attivita' finanziarie.",
    "6": "Accensione di prestiti: mutui e prestiti contratti dall'ente.",
    "7": "Anticipazioni di cassa ricevute dall'istituto tesoriere/cassiere.",
    "9": "Entrate per conto di terzi e partite di giro (es. ritenute, depositi): di pari "
         "importo alle relative uscite, NON costituiscono entrata effettiva.",
}


def missione_desc(code) -> tuple[str, str] | None:
    """``(description, source)`` for a spending missione code, or None."""
    c = "" if code is None else str(code).strip().zfill(2)
    return (MISSIONI[c], SRC_MISSIONI) if c in MISSIONI else None


def titolo_desc(code) -> tuple[str, str] | None:
    """``(description, source)`` for a revenue titolo code, or None."""
    c = "" if code is None else str(code).strip()
    return (TITOLI[c], SRC_TITOLI) if c in TITOLI else None
