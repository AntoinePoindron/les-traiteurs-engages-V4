(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var canvas = document.getElementById('revenueChart');
    if (!canvas || typeof Chart === 'undefined') return;

    var labels = JSON.parse(canvas.dataset.labels || '[]');
    var data = JSON.parse(canvas.dataset.revenue || '[]');

    new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Revenu (EUR)',
          data: data,
          backgroundColor: '#1A3A52',
          borderRadius: 6,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { callback: function (v) { return v + ' €'; } }
          }
        }
      }
    });
  });
})();
