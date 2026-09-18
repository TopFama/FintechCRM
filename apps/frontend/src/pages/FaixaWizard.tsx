import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Template, WhatsappNumber } from "../api";

export default function FaixaWizard() {
  const [step, setStep] = useState(1);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [numberIds, setNumberIds] = useState<string[]>([]);
  const [columnByVariable, setColumnByVariable] = useState<Record<string, string>>({});

  useEffect(() => {
    api.listTemplates().then(setTemplates).catch((e) => setError(e.message));
    api.listNumbers().then(setNumbers).catch((e) => setError(e.message));
  }, []);

  const navigate = useNavigate();
  const selectedTemplate = templates.find((t) => t.id === templateId);

  function toggleNumber(id: string) {
    setNumberIds((prev) => (prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id]));
  }

  async function handleCreate() {
    if (!selectedTemplate) return;
    setError(null);
    try {
      const variable_mappings = selectedTemplate.variables.map((v) => ({
        template_variable_id: v.id,
        column_name: columnByVariable[v.id] || v.internal_name,
      }));
      const faixa = await api.createFaixa({
        name,
        template_id: templateId,
        whatsapp_number_ids: numberIds,
        variable_mappings,
      });
      navigate(`/faixas/${faixa.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao criar faixa");
    }
  }

  return (
    <div>
      <h2>Nova faixa de cobrança</h2>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        {step === 1 && (
          <>
            <h3>1. Nome da faixa e template</h3>
            <div className="field">
              <label>Nome da faixa (ex. RENEGOCIE, 21 A 30)</label>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label>Template aprovado</label>
              <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">Selecione...</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.status})
                  </option>
                ))}
              </select>
            </div>
            <button disabled={!name || !templateId} onClick={() => setStep(2)}>
              Próximo
            </button>
          </>
        )}

        {step === 2 && (
          <>
            <h3>2. Números de envio</h3>
            <p style={{ color: "#64748b" }}>
              Selecione um ou mais números. Quando mais de um for escolhido, os disparos alternam
              entre eles.
            </p>
            {numbers.map((n) => (
              <label key={n.id} style={{ display: "block", marginBottom: 6 }}>
                <input
                  type="checkbox"
                  style={{ width: "auto", marginRight: 6 }}
                  checked={numberIds.includes(n.id)}
                  onChange={() => toggleNumber(n.id)}
                />
                {n.label || n.display_phone_number} ({n.display_phone_number})
              </label>
            ))}
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button className="secondary" onClick={() => setStep(1)}>
                Voltar
              </button>
              <button disabled={numberIds.length === 0} onClick={() => setStep(3)}>
                Próximo
              </button>
            </div>
          </>
        )}

        {step === 3 && selectedTemplate && (
          <>
            <h3>3. Variáveis internas → colunas da planilha</h3>
            <p style={{ color: "#64748b" }}>
              Para cada variável do template, informe o nome da coluna que vai existir na planilha de
              clientes dessa faixa.
            </p>
            {selectedTemplate.variables.length === 0 && <p>Este template não tem variáveis no corpo.</p>}
            {selectedTemplate.variables.map((v) => (
              <div className="field" key={v.id}>
                <label>Variável interna: {v.internal_name}</label>
                <input
                  value={columnByVariable[v.id] || v.internal_name}
                  onChange={(e) => setColumnByVariable({ ...columnByVariable, [v.id]: e.target.value })}
                />
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button className="secondary" onClick={() => setStep(2)}>
                Voltar
              </button>
              <button onClick={handleCreate}>Criar faixa</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
