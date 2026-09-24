import { Fragment, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Template, WhatsappNumber } from "../api";
import { IconAlert, IconCheckCircle } from "../icons";

const STEPS = [
  { n: 1, label: "Nome e template" },
  { n: 2, label: "Números de envio" },
  { n: 3, label: "Variáveis" },
];

function Stepper({ step }: { step: number }) {
  return (
    <div className="stepper">
      {STEPS.map((s, i) => (
        <Fragment key={s.n}>
          <div className={`stepper-step${step === s.n ? " active" : ""}${step > s.n ? " done" : ""}`}>
            <div className="stepper-circle">{step > s.n ? <IconCheckCircle width={16} height={16} /> : s.n}</div>
            <div className="stepper-label">{s.label}</div>
          </div>
          {i < STEPS.length - 1 && <div className={`stepper-line${step > s.n ? " done" : ""}`} />}
        </Fragment>
      ))}
    </div>
  );
}

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
      <div className="page-header">
        <div>
          <h2>Nova faixa de cobrança</h2>
          <div className="subtitle">Dê um nome livre à faixa (ex. "21 A 30" ou "RENEGOCIE") e ligue a um template</div>
        </div>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="card">
        <Stepper step={step} />

        {step === 1 && (
          <>
            <h3>Nome da faixa e template</h3>
            <p className="card-subtitle">O nome é livre — use o rótulo que fizer sentido para a sua régua de cobrança.</p>
            <div className="field">
              <label htmlFor="wizard-nome-da-faixa">Nome da faixa</label>
              <input id="wizard-nome-da-faixa"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ex. RENEGOCIE, 21 A 30"
              />
            </div>
            <div className="field">
              <label htmlFor="wizard-template-aprovado">Template aprovado</label>
              <select id="wizard-template-aprovado" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">Selecione...</option>
                {templates
                  .filter((t) => t.status === "approved")
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} ({t.language})
                    </option>
                  ))}
              </select>
            </div>
            <div className="actions-row">
              <button disabled={!name || !templateId} onClick={() => setStep(2)}>
                Próximo
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h3>Números de envio</h3>
            <p className="card-subtitle">
              Selecione um ou mais números. Quando mais de um for escolhido, os disparos alternam entre eles.
            </p>
            <div className="option-list">
              {numbers.map((n) => (
                <label key={n.id} className={`option-item${numberIds.includes(n.id) ? " checked" : ""}`}>
                  <input type="checkbox" checked={numberIds.includes(n.id)} onChange={() => toggleNumber(n.id)} />
                  {n.label || n.display_phone_number} ({n.display_phone_number})
                </label>
              ))}
              {numbers.length === 0 && (
                <p className="text-muted">Nenhum número ainda — importe os números da WABA em Configurações → Tokens da Meta.</p>
              )}
            </div>
            <div className="actions-row">
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
            <h3>Variáveis internas → modelo de planilha</h3>
            <p className="card-subtitle">
              Defina o nome de coluna sugerido para cada variável — vira o cabeçalho do modelo de planilha para
              download. Ao subir a planilha de verdade, você poderá reconferir esse mapeamento escolhendo a coluna
              real em uma lista suspensa, então não precisa ser exato.
            </p>
            {selectedTemplate.variables.length === 0 && <p className="text-muted">Este template não tem variáveis no corpo.</p>}
            {selectedTemplate.variables.map((v) => (
              <div className="field" key={v.id}>
                <label htmlFor={`wizard-var-${v.id}`}>Variável interna: {v.internal_name}</label>
                <input id={`wizard-var-${v.id}`}
                  value={columnByVariable[v.id] || v.internal_name}
                  onChange={(e) => setColumnByVariable({ ...columnByVariable, [v.id]: e.target.value })}
                />
              </div>
            ))}
            <div className="actions-row">
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
