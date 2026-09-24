import RemarketingCard from "../components/config/RemarketingCard";
import RenegocieConexaoCard from "../components/config/RenegocieConexaoCard";

export default function Remarketing() {
  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Remarketing</h2>
          <div className="subtitle">
            Clientes que desistiram da proposta no portal Renegocie: conexão, filtros por segmento e prévia de quem
            entraria hoje
          </div>
        </div>
      </div>

      <RenegocieConexaoCard />
      <div style={{ marginTop: 16 }}>
        <RemarketingCard />
      </div>
    </div>
  );
}
