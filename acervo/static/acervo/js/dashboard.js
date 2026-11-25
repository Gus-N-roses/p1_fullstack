// Desenha o gráfico de empréstimos por mês com os dados que a view escreveu na página
// ({{ ...|json_script:"dados-mes" }}). Sem dados, o template não cria o canvas.
const canvas = document.getElementById('grafico-mensal');

if (canvas) {
  const dados = JSON.parse(document.getElementById('dados-mes').textContent);

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: dados.map(d => d.mes),
      datasets: [{label: 'Empréstimos', data: dados.map(d => d.total), backgroundColor: '#5c1d16'}],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {legend: {display: false}},
      scales: {y: {beginAtZero: true, ticks: {precision: 0}}},
    },
  });
}
