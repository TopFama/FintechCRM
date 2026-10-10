import { IconAlert } from "../icons";

// Templates recategorizados pela Meta e ainda sem Ciente (texto vem do backend)
export default function AvisosCategoria({ avisos }: { avisos: string[] }) {
  if (avisos.length === 0) return null;
  return (
    <div className="warning-box" role="status">
      <IconAlert width={16} height={16} />
      <div>
        {avisos.map((a) => (
          <div key={a}>{a}</div>
        ))}
      </div>
    </div>
  );
}
