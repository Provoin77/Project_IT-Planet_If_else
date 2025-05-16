var map;
var allPlacemarks = [];


function initFavoritesPanel() {
    const toggle   = document.getElementById('favorites-toggle');
    const panel    = document.getElementById('favorites-panel');
    const closeBtn = document.getElementById('favorites-close');
    if (!toggle || !panel || !closeBtn) return;

    toggle.addEventListener('click', () => {
        panel.classList.toggle('open');
        // скрываем сам значок
        toggle.style.display = 'none';
    });
    closeBtn.addEventListener('click', () => {
        panel.classList.remove('open');
        // возвращаем значок
        toggle.style.display = '';
    });

  }

// === Рендер списка в панели ===
function renderSingle(type, value) {
    let ul;
    if (type === 'event')        ul = document.getElementById('fav-events-list');
    else if (type === 'sphere')   ul = document.getElementById('fav-spheres-list');
    else if (type === 'type')     ul = document.getElementById('fav-types-list');
    else if (type === 'organizer')ul = document.getElementById('fav-organizers-list');
    if (!ul || !value) return;

    let text = value;
    if (type === 'event') {
      const ev = eventsData.find(e => e.id.toString() === value.toString());
      text = ev ? ev.title : text;
    }
    if (ul.querySelector(`li[data-fav-value="${value}"]`)) return;

    const li = document.createElement('li');
    li.dataset.favValue = value;
    li.innerHTML = `
      <span>${text}</span>
      <button class="fav-remove"
              data-fav-type="${type}"
              data-fav-value="${value}"
              title="Удалить из избранного">🗑️</button>
    `;
    ul.appendChild(li);
  }
  function renderPanel() {
    ['events','spheres','types','organizers'].forEach(cat => {
      const ul = document.getElementById(`fav-${cat}-list`);
      if(ul) ul.innerHTML = '';
    });
    favoritesData.forEach(f => renderSingle(f.type, f.value));
  }

  // === Управление звёздочками ===
  function initFavorites() {
    // 1) Выставляем начальный вид для всех звёздочек
    document.querySelectorAll('.fav-star').forEach(function(star) {
        var type = star.dataset.favType;
        var val  = star.dataset.favValue;
        var isFav = favoritesData.some(function(f) {
            return f.type === type && f.value.toString() === val.toString();
        });
        star.textContent = isFav ? '★' : '☆';
        star.classList.toggle('favorited', isFav);
    });

    // 2) Обработчик клика по звёздочке (в списке и в балуне)
    document.addEventListener('click', function(e) {
        // 1) Только по нашим звёздочкам
        if (!e.target.classList.contains('fav-star')) return;

        // 2) Только для участников
        if (currentUserRole !== 'participant') {
            alert('Функция избранного доступна только участникам.');
            return;
        }


        var star = e.target;
        var type = star.dataset.favType;
        var val  = star.dataset.favValue;

        fetch('/favorites/toggle', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: type, value: val })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;

            // 2a) Обновляем массив favoritesData
            if (data.action === 'added') {
                favoritesData.push({ type: type, value: val });
            } else {
                favoritesData = favoritesData.filter(function(f) {
                    return !(f.type === type && f.value.toString() === val.toString());
                });
            }

            // 2b) Перерисовываем все звёздочки этого элемента
            document.querySelectorAll('.fav-star[data-fav-type="' + type + '"][data-fav-value="' + val + '"]')
                .forEach(function(s) {
                    if (data.action === 'added') {
                        s.textContent = '★';
                        s.classList.add('favorited');
                    } else {
                        s.textContent = '☆';
                        s.classList.remove('favorited');
                    }
                });

           // 2c) Если это событие — обновляем балун на карте
            if (type === 'event') {
              allPlacemarks.forEach(function(item) {
                if (!item.ids || !item.ids.includes(parseInt(val, 10))) return;
                const evObj = eventsData.find(o => o.id === parseInt(val, 10));

                if (item.ids.length === 1) {
                  // обычная метка: перерисуем одиночный балун
                  item.placemark.properties.set(
                    'balloonContent',
                    generateBalloonContent(evObj)
                  );
                } else {
                  // кластер: пересобираем сохранённый HTML
                  const group = item.ids.map(id => eventsData.find(e => e.id === id));
                  item.clusterHtml = generateClusterBalloonContent(group);

                  // только если кластер именно сейчас открыт — покажем обновлённый
                  if (item.placemark.balloon.isOpen()) {
                    item.placemark.properties.set('balloonContent', item.clusterHtml);
                  }
                }
              });
            }

            // 2d) Если добавлено — отрисовать в панели, если удалено — убрать
            if (data.action === 'added') {
                renderSingle(type, val);
            } else {
                var li = document.querySelector(
                    '#fav-' + (type === 'event' ? 'events' : type + 's') +
                    '-list li[data-fav-value="' + val + '"]'
                );
                if (li) li.remove();
            }
        });
    });

    // 3) Обработчик клика по “мусорке” в панели
    document.addEventListener('click', function(e) {
        if (!e.target.classList.contains('fav-remove')) return;
        var btn  = e.target;
        var type = btn.dataset.favType;
        var val  = btn.dataset.favValue;

        fetch('/favorites/toggle', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: type, value: val })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;

            // 3a) Обновляем массив
            favoritesData = favoritesData.filter(function(f) {
                return !(f.type === type && f.value.toString() === val.toString());
            });

            // 3b) Убираем пункт из панели
            var li = btn.closest('li');
            if (li) li.remove();

            // 3c) Сбрасываем все звёздочки этого элемента на странице
            document.querySelectorAll('.fav-star[data-fav-type="' + type + '"][data-fav-value="' + val + '"]')
                .forEach(function(s) {
                    s.textContent = '☆';
                    s.classList.remove('favorited');
                });

            // 3d) Обновляем балун, если это событие
            if (type === 'event') {
                allPlacemarks.forEach(function(item) {
                      // для одиночных меток — item.ids = [ev.id], для кластеров — массив >1
                      if (item.ids && item.ids.includes(parseInt(val, 10))) {
                        const evObj = eventsData.find(o => o.id === parseInt(val, 10));
                        // если это кластер, то лучше обновить и item.clusterHtml, но для начала
                        // хотя бы подменим сразу открытый балун
                        item.placemark.properties.set(
                          'balloonContent',
                          generateBalloonContent(evObj)
                        );
                      }
                    });
            }
        });
    });
}



if (
    document.getElementById('map') &&
    typeof ymaps !== 'undefined' &&
    typeof eventsData !== 'undefined'
  ) {
      ymaps.ready(initMap);
  }


function initMap() {
    console.log("DEBUG: initMap вызвана");
    // Рассчитываем центр и масштаб по данным eventsData
    var center, zoomLevel;
    if (typeof eventsData === 'undefined' || eventsData.length === 0) {
        center = [55.751244, 37.618423];
        zoomLevel = 5;
    } else if (eventsData.length === 1) {
        center = [eventsData[0].lat, eventsData[0].lon];
        zoomLevel = 12;
    } else {
        var totalLat = 0, totalLon = 0, count = 0;
        eventsData.forEach(function(ev) {
            if (ev.lat && ev.lon) {
                totalLat += ev.lat;
                totalLon += ev.lon;
                count++;
            }
        });
        if (count === 0) {
            center = [55.751244, 37.618423];
            zoomLevel = 5;
        } else {
            center = [totalLat / count, totalLon / count];
            zoomLevel = 10;
        }
    }

    console.log("DEBUG: Центр карты:", center, "Масштаб:", zoomLevel);

    // Создаём карту
    map = new ymaps.Map('map', {
        center: center,
        zoom: zoomLevel,
        controls: ['zoomControl', 'fullscreenControl']
    });

    // Отрисовываем метки по всем событиям, если переменная eventsData определена
    if (typeof eventsData !== 'undefined') {
      updateMapMarkers(eventsData);
    }
}

// Перехват события submit для всех форм с классом "ajax-subscription"
document.addEventListener('submit', function(e) {
    var form = e.target;
    if (!form.classList.contains('ajax-subscription')) return;

    console.log("DEBUG: Отправка формы ajax-subscription для event_id:", form.getAttribute('data-event-id'));
    e.preventDefault();
    handleSubscriptionForm(form);
});

function handleSubscriptionForm(form) {
  var url = form.getAttribute('action');
  var method = form.getAttribute('method') || 'POST';
  var eventId = form.getAttribute('data-event-id');
  console.log("DEBUG: Отправка запроса", method, "на URL:", url, "для event_id:", eventId);

  var formData = new FormData(form);
  fetch(url, {
    method: method,
    body: formData,
    headers: {
      'X-Requested-With': 'XMLHttpRequest'
    },
    credentials: 'same-origin'
  })
    .then(response => {
      console.log(
        "DEBUG: Получен ответ от сервера для event_id:",
        eventId,
        "Status:",
        response.status
      );
      if (!response.ok) {
        // Если сервер вернул ошибку (4xx или 5xx)
        return response.json()
          .then(errData => {
            // пробрасываем тело ошибки дальше
            return Promise.reject(errData);
          })
          .catch(() => {
            // не удалось распарсить JSON
            return Promise.reject({
              message: `Сервер вернул статус ${response.status}`
            });
          });
      }
      // иначе возвращаем JSON из успешного ответа
      return response.json();
    })
    .then(data => {
      console.log(
        "DEBUG: Данные из сервера для event_id:",
        eventId,
        data
      );
      if (data.success) {
        updateSubscriptionUI(data.event_id, data.subscribed);
        console.log(
          "DEBUG: Обновлено состояние для event_id:",
          data.event_id,
          "Новое состояние: subscribed =",
          data.subscribed
        );
      } else {
        console.error(
          "DEBUG: Ошибка в payload для event_id:",
          eventId,
          data.message
        );
        alert(data.message || 'Не удалось выполнить операцию.');
      }
    })
    .catch(err => {
      console.error(
        "DEBUG: Ошибка запроса для event_id:",
        eventId,
        err
      );
      alert(err.message || 'Ошибка соединения с сервером.');
    });
}


function updateSubscriptionUI(event_id, subscribed) {
  console.log("DEBUG: updateSubscriptionUI для event_id:", event_id, "Состояние:", subscribed);

  // 1) Обновляем кнопки в формах подписки/отписки
  document.querySelectorAll('form.ajax-subscription[data-event-id="' + event_id + '"]').forEach(form => {
    if (subscribed) {
      form.action = '/unsubscribe/' + event_id;
      form.querySelector('button').textContent = 'Отписаться';
    } else {
      form.action = '/subscribe/' + event_id;
      form.querySelector('button').textContent = 'Записаться';
    }
  });

  // 2) Обновляем модель в memory
  const evIndex = eventsData.findIndex(ev => ev.id === parseInt(event_id, 10));
  if (evIndex !== -1) {
    eventsData[evIndex].subscribed = subscribed;
  }

  // 3) Обновляем балуны на карте
  allPlacemarks.forEach(item => {
    // если метка или кластер содержит наше событие
    if (!item.ids || !item.ids.includes(parseInt(event_id, 10))) return;

    if (item.ids.length === 1) {
      // одиночная метка — рендерим её балун
      const evObj = eventsData.find(ev => ev.id === parseInt(event_id, 10));
      item.placemark.properties.set(
        'balloonContent',
        generateBalloonContent(evObj)
      );
    } else {
      // кластер — пересобираем сохранённый HTML
      const group = item.ids.map(id => eventsData.find(ev => ev.id === id));
      item.clusterHtml = generateClusterBalloonContent(group);

      // если кластерный балун сейчас открыт — подменяем содержимое
      if (item.placemark.balloon.isOpen()) {
        item.placemark.properties.set('balloonContent', item.clusterHtml);
      }
    }
  });
}


// Функция генерации содержимого балуна для события ev
// Генерация содержимого балуна, плюс строка с приоритетом
function generateBalloonContent(ev) {
  // 1) Заголовок + звёздочка избранного
  let starHtml = '';
  if (currentUserRole === 'participant') {
    const isFav = favoritesData.some(f => f.type === 'event' && String(f.value) === String(ev.id));
    starHtml = `
      <span class="${isFav ? 'fav-star favorited' : 'fav-star'}"
            data-fav-type="event"
            data-fav-value="${ev.id}"
            title="В избранное"
            style="cursor:pointer; font-size:1.2rem; vertical-align:middle; margin-left:5px;">
        ${isFav ? '★' : '☆'}
      </span>
    `;
  }

  // 2) Приоритет
  let priorityHtml = '';
  if (ev.priority > 0) {
    priorityHtml = `<div style="margin:6px 0; font-weight:600; color:#197d19;">
                      Приоритет: ${ev.priority}
                    </div>`;
  }

  // 3) Персоналии
  let personalitiesHtml = '';
  if (ev.personalities && ev.personalities.length) {
    personalitiesHtml = `
      <div style="background: #fff3cd; padding:4px; margin:6px 0; border-radius:4px;">
        <b>Гости:</b> ${ev.personalities.join(', ')}
      </div>
    `;
  }

  // 4) Остальной контент
  let content = `
    <strong>${ev.title}${starHtml}</strong><br>
    ${priorityHtml}
    Организатор: ${ev.organizer || '—'}<br>
    Формат: ${ev.event_format === 'online' ? 'Онлайн' : 'Офлайн'}<br>
    Место: ${ev.city}${ev.event_format==='offline' && ev.address ? ', '+ev.address : ''}<br>
    Дата: ${ev.date}<br>
    <strong>Статус:</strong> ${ev.status}
    ${personalitiesHtml}
    <br>
    <a href="/events/${ev.id}"
       style="color:#004cfd; text-decoration:none; font-weight:500;">
      Подробнее
    </a>
  `;

  // 5) Кнопки подписки (только для участников)
  if (currentUserRole === 'participant') {
    if (ev.status === 'предстоит') {
      content += ev.subscribed
        ? `<br><form method="post" action="/unsubscribe/${ev.id}" class="ajax-subscription" data-event-id="${ev.id}">
             <button>Отписаться</button>
           </form>`
        : `<br><form method="post" action="/subscribe/${ev.id}" class="ajax-subscription" data-event-id="${ev.id}">
             <button>Записаться</button>
           </form>`;
    } else if (ev.status === 'проходит') {
      content += `<br><span style="color:green;">Мероприятие проходит</span>`;
    }
  }

  // 6) Обёртка
  return `
    <div style="font-family:Inter,sans-serif;font-size:1.1rem;line-height:1.4;color:#222;">
      ${content}
    </div>
  `;
}


function showClusterEvent(eventId) {
  console.log("DEBUG: showClusterEvent для event_id:", eventId);
  var item = allPlacemarks.find(it => it.ids.includes(eventId));
  if (!item) { console.warn("Не найден кластер для", eventId); return; }

  var ev = eventsData.find(e => e.id === eventId);
  if (!ev) return;

  if (!item._clusterHtml) item._clusterHtml = item.clusterHtml;

  // ВАЖНО: ставим + между каждой строкой
  var singleHtml =
    generateBalloonContent(ev) +
    '<div style="text-align:right; margin-top:8px;">' +
      '<button onclick="restoreCluster(' + eventId + ')"' +
              ' style="background:transparent; border:none; font-size:1.2rem; cursor:pointer;">' +
        '×' +
      '</button>' +
    '</div>';

  item.placemark.properties.set('balloonContent', singleHtml);
  item.placemark.balloon.open();

  item.placemark.events.once('balloonclose', function(){
    restoreCluster(eventId);
  });
}


function generateClusterBalloonContent(group) {
  // Первый фрагмент
  var html =
    '<div style="font-family:Inter, sans-serif; font-size:1rem; color:#222; max-width:300px;">' +
      '<input type="text" id="cluster-search-input" ' +
         'placeholder="Поиск по названию..." ' +
         'oninput="clusterFilter(this.value)" ' +
         'style="width:100%; padding:6px; margin-bottom:8px; box-sizing:border-box;"/>' +
      '<div id="cluster-empty" ' +
           'style="display:none; padding:10px; color:#555; font-style:italic;">' +
        'Не удалось найти мероприятия с таким названием.' +
      '</div>' +
      '<div style="max-height:150px; min-height:130px; overflow-y:auto;">' +
        '<ul id="cluster-events-list" style="list-style:none; padding:0; margin:0;">';

  group.forEach(function(ev) {
    var isFav       = favoritesData.some(f => f.type==='event' && f.value.toString()===ev.id.toString());
    var starChar    = isFav ? '★' : '☆';
    var starClass   = isFav ? 'fav-star favorited' : 'fav-star';
    var hasPers     = ev.personalities && ev.personalities.length > 0;
    // если есть персоналия — подсветка
    var itemBgStyle = hasPers
      ? 'background-color:#fff9c4; padding:4px; border-radius:4px; '
      : '';
    // общий стиль li
    var liStyle = itemBgStyle + 'margin-bottom:6px; display:flex; align-items:center;';

    html +=
      '<li data-ev-id="' + ev.id + '" data-ev-title="' + ev.title + '"' +
          ' style="' + liStyle + '">' +
        '<a href="javascript:showClusterEvent(' + ev.id + ')"' +
           ' style="font-weight:600; color:#004cfd; text-decoration:none; flex:1;">' +
           ev.title +
        '</a>' +
        '<span class="' + starClass + '"' +
              ' data-fav-type="event" data-fav-value="' + ev.id + '"' +
              ' title="В избранное"' +
              ' style="cursor:pointer; margin-left:8px; font-size:1.2em;">' +
          starChar +
        '</span>' +
        '<a href="/events/' + ev.id + '"' +
           ' style="margin-left:8px; font-size:0.9rem; color:#004cfd; text-decoration:none;">' +
           'Подробнее' +
        '</a>' +
      '</li>';
  });

  html +=
        '</ul>' +
      '</div>' +
    '</div>';

  return html;
}




function restoreCluster(eventId) {
    var item = allPlacemarks.find(it=>it.ids.includes(eventId));
    if (!item || !item._clusterHtml) return;
    item.placemark.properties.set('balloonContent', item._clusterHtml);
    item.placemark.balloon.open();
}


function clusterFilter(term) {
    term = term.toLowerCase();
    var listNode = document.getElementById('cluster-events-list');
    var emptyNode = document.getElementById('cluster-empty');
    if (!listNode || !emptyNode) return;
    var anyVisible = false;
    listNode.querySelectorAll('li').forEach(function(li) {
        var title = li.dataset.evTitle.toLowerCase();
        if (title.includes(term)) {
            li.style.display = '';
            anyVisible = true;
        } else {
            li.style.display = 'none';
        }
    });
    emptyNode.style.display = anyVisible ? 'none' : 'block';
}


// Отрисовка меток на карте (только на главной странице, где eventsData определена)
// Пересоздаёт все метки на карте с учётом поля ev.priority
// Отрисовка меток на карте (только на главной странице, где eventsData определена)
// Пересоздаёт все метки на карте с учётом поля ev.priority
function updateMapMarkers(filteredEvents) {
  map.geoObjects.removeAll();
  allPlacemarks = [];

  // Группируем онлайн-события по координатам
  const onlineGroups = {};
  filteredEvents.forEach(ev => {
    if (ev.event_format === 'online' && ev.lat && ev.lon) {
      const key = ev.lat.toFixed(6) + ',' + ev.lon.toFixed(6);
      (onlineGroups[key] = onlineGroups[key] || []).push(ev);
    }
  });

  // Одиночные метки
  filteredEvents.forEach(ev => {
    if (!ev.lat || !ev.lon) return;
    const key = ev.lat.toFixed(6) + ',' + ev.lon.toFixed(6);
    const group = onlineGroups[key] || [];
    // Если онлайн-группа больше 1, её обработаем ниже как кластер
    if (ev.event_format === 'online' && group.length > 1) return;

    // Выбираем иконку по приоритету, гостям, формату
    let preset;
    if (ev.priority > 0) {
      preset = 'islands#greenDotIcon';
    } else if (ev.personalities && ev.personalities.length) {
      preset = 'islands#yellowDotIcon';
    } else if (ev.event_format === 'online') {
      preset = 'islands#redCircleDotIconWithCaption';
    } else {
      preset = 'islands#blueDotIconWithCaption';
    }

    const placemark = new ymaps.Placemark(
      [ev.lat, ev.lon],
      {
        balloonContent: generateBalloonContent(ev),
        iconCaption: ev.title
      },
      { preset }
    );
    map.geoObjects.add(placemark);
    allPlacemarks.push({ ids: [ev.id], placemark });
  });

  // Кластеры онлайн-событий
  Object.values(onlineGroups).forEach(group => {
    if (group.length < 2) return;
    const lat = group[0].lat, lon = group[0].lon;

    // Иконка кластера: зелёная, если в группе есть приоритет, иначе жёлтая/красная
    const hasPriority = group.some(ev => ev.priority > 0);
    const hasPers = group.some(ev => ev.personalities && ev.personalities.length);
    let clusterPreset;
    if (hasPriority) {
      clusterPreset = 'islands#greenDotIcon';
    } else if (hasPers) {
      clusterPreset = 'islands#yellowDotIcon';
    } else {
      clusterPreset = 'islands#redCircleDotIconWithCaption';
    }

    const html = generateClusterBalloonContent(group);
    const placemark = new ymaps.Placemark(
      [lat, lon],
      { balloonContent: html, balloonContentHeader: `Онлайн: ${group.length}` },
      { preset: clusterPreset }
    );
    map.geoObjects.add(placemark);
    allPlacemarks.push({ ids: group.map(e=>e.id), placemark, clusterHtml: html });
  });

  // Центрируем и масштабируем так, чтобы все точки были в пределах видимости
  const bounds = map.geoObjects.getBounds();
  if (bounds) {
    map.setBounds(bounds, {
      checkZoomRange: true,
      zoomMargin: 50
    });
  }
}

/**
 * Рендерит плитки .event-card на главной странице по массиву filteredEvents.
 * Показывает обложку из static/uploads/meropimage/ev.image_filename или плейсхолдер.
 */
function updateEventList(filteredEvents) {
  console.log("DEBUG: updateEventList", filteredEvents.length);
  const container = document.getElementById('event-list');
  container.innerHTML = '';

  if (filteredEvents.length === 0) {
    container.innerHTML = '<p>Нет мероприятий по выбранным фильтрам.</p>';
    return;
  }

  filteredEvents.forEach(ev => {
    // контейнер карточки
    const card = document.createElement('div');
    card.className = 'event-card';

    // изображение или заглушка
    if (ev.image_filename) {
      const img = document.createElement('img');
      // теперь отдаем по нашему маршруту
      img.src = `/uploads/meropimage/${ev.image_filename}`;
      img.alt = ev.title;
      card.appendChild(img);
    } else {
      const noImg = document.createElement('div');
      noImg.className = 'no-image';
      noImg.textContent = 'Картинка скоро появится';
      card.appendChild(noImg);
    }

    // тело карточки
    const body = document.createElement('div');
    body.className = 'event-card-body';

    // заголовок + ссылка
    const h5 = document.createElement('h5');
    const link = document.createElement('a');
    link.href = `/events/${ev.id}`;
    link.textContent = ev.title;
    h5.appendChild(link);
    if (ev.priority > 0) {
      const pb = document.createElement('span');
      pb.className = 'priority-badge';
      pb.textContent = 'P' + ev.priority;
      h5.appendChild(pb);
    }
    body.appendChild(h5);

    // дата
    const dateP = document.createElement('div');
    dateP.textContent = ev.date;
    dateP.style.fontSize = '0.85rem';
    dateP.style.color = '#666';
    dateP.style.marginBottom = '8px';
    body.appendChild(dateP);

    // бейджи
    const badges = document.createElement('div');
    badges.className = 'badges';
    const tBadge = document.createElement('span');
    tBadge.className = 'badge bg-info text-dark';
    tBadge.textContent = ev.event_type;
    const sBadge = document.createElement('span');
    sBadge.className = 'badge bg-secondary';
    sBadge.textContent = ev.event_sphere;
    badges.append(tBadge, sBadge);
    body.appendChild(badges);

    // доп. инфо (организатор, город)
    const info = document.createElement('p');
    info.style.marginTop = 'auto';
    info.textContent = (ev.organizer || '—') + ', ' + ev.city +
      (ev.event_format === 'offline' && ev.address ? ', ' + ev.address : '');
    body.appendChild(info);

    card.appendChild(body);

    // футер с кнопками
    const footer = document.createElement('div');
    footer.className = 'event-card-footer';

    // избранное
    if (currentUserRole === 'participant') {
      const star = document.createElement('span');
      star.className = 'fav-star';
      star.dataset.favType = 'event';
      star.dataset.favValue = ev.id;
      const isFav = favoritesData.some(f => f.type==='event' && f.value == ev.id);
      star.textContent = isFav ? '★' : '☆';
      footer.appendChild(star);
    }

    // маркер
    const marker = document.createElement('span');
    marker.className = 'map-marker';
    marker.textContent = '📍';
    marker.onclick = () => centerMapOnEvent(ev.id);
    footer.appendChild(marker);

    // кнопка подписки/отписки
    if (currentUserRole === 'participant') {
      if (ev.status === 'предстоит') {
        const form = document.createElement('form');
        form.className = 'ajax-subscription';
        form.method = 'post';
        form.action = (ev.subscribed ? '/unsubscribe/' : '/subscribe/') + ev.id;
        form.dataset.eventId = ev.id;
        form.style.display = 'inline';

        const btn = document.createElement('button');
        btn.type = 'submit';
        btn.textContent = ev.subscribed ? 'Отписаться' : 'Записаться';
        form.appendChild(btn);
        footer.appendChild(form);

      } else if (ev.status === 'проходит') {
        const now = document.createElement('span');
        now.style.color = 'green';
        now.textContent = 'Идёт сейчас';
        footer.appendChild(now);
      }
    }

    card.appendChild(footer);
    container.appendChild(card);
  });
}




// Функция фильтрации событий по введённым параметрам
function filterEvents() {
    console.log("DEBUG: filterEvents запущена");
    var filterTitle = document.getElementById('filter-title').value.toLowerCase();
    var filterOrganizer = document.getElementById('filter-organizer').value.toLowerCase();
    var filterCity = document.getElementById('filter-city').value.toLowerCase();
    var filterSphere = document.getElementById('filter-sphere').value;
    var filterType = document.getElementById('filter-type').value;
    var filterFormat = document.getElementById('filter-format').value;

    var filtered = eventsData.filter(function(ev) {
        var match = true;
        if (filterTitle && !ev.title.toLowerCase().includes(filterTitle)) match = false;
        if (filterOrganizer && !(ev.organizer && ev.organizer.toLowerCase().includes(filterOrganizer))) match = false;
        if (filterCity && !(ev.city && ev.city.toLowerCase().includes(filterCity))) match = false;
        if (filterSphere && ev.event_sphere !== filterSphere) match = false;
        if (filterType && ev.event_type !== filterType) match = false;
        if (filterFormat && ev.event_format !== filterFormat) match = false;
        return match;
    });

    console.log("DEBUG: filterEvents отфильтровал", filtered.length, "событий");
    updateEventList(filtered);
    updateMapMarkers(filtered);
}


function filterByFavorites() {
    // если ничего нет — просто основной фильтр
    if (!favoritesData.length) {
      filterEvents();
      return;
    }

    // собираем списки значений
    var favEvents     = favoritesData.filter(f => f.type==='event').map(f=>f.value.toString());
    var favSpheres    = favoritesData.filter(f => f.type==='sphere').map(f=>f.value.toLowerCase());
    var favTypes      = favoritesData.filter(f => f.type==='type').map(f=>f.value.toLowerCase());
    var favOrganizers = favoritesData.filter(f => f.type==='organizer').map(f=>f.value.toLowerCase());

    // фильтруем eventsData
    var filtered = eventsData.filter(function(ev){
      // 1) по ID события
      if (favEvents.includes(ev.id.toString())) return true;
      // 2) по организатору
      if (ev.organizer && favOrganizers.includes(ev.organizer.toLowerCase())) return true;
      // 3) по сфере и типу — читаем из <li>
      var li = document.querySelector('li[data-event-id="'+ev.id+'"]');
      if (li) {
        var sp = (li.dataset.sphere||'').toLowerCase();
        var tp = (li.dataset.type  ||'').toLowerCase();
        if (favSpheres.includes(sp)) return true;
        if (favTypes.includes(tp))   return true;
      }
      return false;
    });

    updateEventList(filtered);
    updateMapMarkers(filtered);
  }

  // вешаем на кнопку
  document.addEventListener('DOMContentLoaded', function(){
    var btn = document.getElementById('filter-favorites');
    if (btn) {
      btn.addEventListener('click', function(e){
        e.preventDefault();
        filterByFavorites();
      });
    }
  });

// При клике на иконку в списке центрируем карту и открываем балун соответствующей метки
function centerMapOnEvent(eventId) {
    console.log("DEBUG: centerMapOnEvent запущена для event_id:", eventId);
    var item = allPlacemarks.find(function(it) {
        if (Array.isArray(it.ids)) return it.ids.includes(eventId);
        return it.ids[0] === eventId;
    });
    if (!item) {
        console.warn("DEBUG: Не найден элемент для event_id:", eventId);
        return;
    }
    var ev = eventsData.find(e=>e.id===eventId);
    if (ev && ev.lat && ev.lon) {
        map.setCenter([ev.lat, ev.lon], 14, { checkZoomRange: true });
    }
    if (item.ids.length > 1) {
        // сначала краткий балун по этому событию
        showClusterEvent(eventId);
    } else {
        item.placemark.balloon.open();
    }
}



// Установка обработчиков для динамической фильтрации после загрузки DOM
document.addEventListener('DOMContentLoaded', function() {
    console.log("DEBUG: DOMContentLoaded");
    // Если элементы фильтра присутствуют (это работает только на главной)
    if (document.getElementById('filter-title')) {
      document.getElementById('filter-title').addEventListener('input', filterEvents);
      document.getElementById('filter-organizer').addEventListener('input', filterEvents);
      document.getElementById('filter-city').addEventListener('input', filterEvents);
      document.getElementById('filter-sphere').addEventListener('change', filterEvents);
      document.getElementById('filter-type').addEventListener('change', filterEvents);
      document.getElementById('filter-format').addEventListener('change', filterEvents);

      console.log("DEBUG: Перерисовка списка мероприятий после загрузки страницы");
      updateEventList(eventsData);
    }

    initFavoritesPanel();
    renderPanel();
    initFavorites();


});
