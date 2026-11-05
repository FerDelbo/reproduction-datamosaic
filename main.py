# https://event.cwi.nl/da/PublicBIbenchmark/

from llm.agent import RegulatoryNarrativeAgent, save_docuement, valid_rows_docuemnt

agent = RegulatoryNarrativeAgent(model_name="gpt-4o-mini", model_provider='openai', temperature=0.2)

schema_exemplo = """
    TABLE federal_grant_disbursements (
        disbursement_id VARCHAR(50),
        recipient_uei VARCHAR(12),
        recipient_legal_name TEXT,
        cfda_number VARCHAR(10),
        program_title TEXT,
        disbursement_amount DECIMAL(15, 2),
        fiscal_year INT,
        compliance_risk_score INT
    );
    """

    # 4 instâncias completas a serem camufladas no texto
registros = [
    {
        "disbursement_id": "DSB-2024-8819",
        "recipient_uei": "MNK9L8273641",
        "recipient_legal_name": "Midwest Rural Health Consortium",
        "cfda_number": "93.912",
        "program_title": "Rural Health Care Services Outreach",
        "disbursement_amount": 1420500.00,
        "fiscal_year": 2024,
        "compliance_risk_score": 14
    },
    {
        "disbursement_id": "DSB-2024-9102",
        "recipient_uei": "XPQ1W9928374",
        "recipient_legal_name": "Pacific Biosphere Restoration Taskforce",
        "cfda_number": "15.631",
        "program_title": "Partners for Fish and Wildlife",
        "disbursement_amount": 834200.50,
        "fiscal_year": 2024,
        "compliance_risk_score": 42
    },
]

formato_json_esperado = {
        "report_metadata": {
            "title": "string",
            "regulatory_framework": "string",
            "audit_period": "string"
        },
        "executive_summary": "string",
        "detailed_regulatory_findings": [
            {
                "section_title": "string",
                "narrative_analysis": "string (com dados contextuais embutidos)",
                "statutory_citations": ["string"]
            }
        ],
        "extracted_entity_instances": [
            {
                "disbursement_id": "string",
                "recipient_uei": "string",
                "recipient_legal_name": "string",
                "cfda_number": "string",
                "program_title": "string",
                "disbursement_amount": 0.0,
                "fiscal_year": 0,
                "compliance_risk_score": 0
            }
        ]
    }


resultado = agent.generate(
        table_schema=schema_exemplo,
        records=registros,
        json_exemple=formato_json_esperado
    )

integridade_ok = valid_rows_docuemnt(resultado, registros)
print(f"Status da auditoria de dados: {'APROVADO' if integridade_ok else 'REPROVADO'}")

save_docuement(resultado, "document1.json")