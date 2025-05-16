document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('notifications-toggle');
    const panel  = document.getElementById('notifications-panel');
    const close  = document.getElementById('notifications-close');
    const count  = document.getElementById('notifications-count');
    const list   = document.getElementById('notifications-list');
    const clearAll = document.getElementById('notifications-clear-all');
    const favToggle     = document.getElementById('favorites-toggle');
    const friendsToggle = document.getElementById('friends-toggle');
    

    console.log('DOM загружен, навешиваем handlers на колокольчик и крестик');
  
     // Открытие/закрытие панели уведомлений по колокольчику
    toggle.addEventListener('click', () => {
        const isOpening = !panel.classList.contains('open');
        panel.classList.toggle('open');
        if (isOpening) {
        // только что открыли — скрываем другие иконки
        if (favToggle)     favToggle.style.display = 'none';
        if (friendsToggle) friendsToggle.style.display = 'none';
        } else {
        // закрыли повторным кликом — возвращаем их
        if (favToggle)     favToggle.style.display = '';
        if (friendsToggle) friendsToggle.style.display = '';
        }
    });

    // Закрытие панели по крестику
    close.addEventListener('click', () => {
        panel.classList.remove('open');
        if (favToggle)     favToggle.style.display = '';
        if (friendsToggle) friendsToggle.style.display = '';
    });
        
  
    // Загрузка списка
    async function fetchNotes() {
      try {
        const res = await fetch('/notifications');
        const notes = await res.json();
        renderNotes(notes);
      } catch (e) {
        console.error(e);
      }
    }
  
    // Рендерим иконку кол-во и список
    function renderNotes(notes) {
        // badge
        if (notes.length > 0) {
          count.textContent = notes.length;
          count.style.display = 'inline-block';
        } else {
          count.style.display = 'none';
        }
      
        // список
        list.innerHTML = '';
        notes.forEach(n => {
          // определяем URL для «Перейти»
          let url = n.url; // теперь берём прямо из ответа
          if (n.message.includes('организатора')) {
            url = '/organizers';              // страница модерации заявок организаторов
          } else if (n.message.includes('мероприятие')) {
            url = '/moderator/events';        // страница модерации мероприятий
          }
      
          const li = document.createElement('li');
          li.innerHTML = `
            <span>${n.message}</span>
            <div class="note-actions">
              ${n.url ? `<a href="${n.url}" class="go-to">Перейти</a>` : ''}
              <button class="delete-note" data-id="${n.id}">🗑️</button>
            </div>
          `;
          list.appendChild(li);
        });
      }
  
    // Удаление одного
    list.addEventListener('click', e => {
      if (!e.target.classList.contains('delete-note')) return;
      const id = e.target.dataset.id;
      fetch('/notifications/' + id, { method: 'DELETE' })
        .then(() => fetchNotes());
    });
  
    // Очистить всё
    clearAll.addEventListener('click', () =>
      fetch('/notifications/clear_all', { method: 'DELETE' })
        .then(() => fetchNotes())
    );
  
    // опрос каждые 2сек
    setInterval(fetchNotes, 2000);
    // сразу загрузить раз
    fetchNotes();
  });
  