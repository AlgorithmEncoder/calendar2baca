document.querySelectorAll('.custom-select').forEach(select => {
    const trigger = select.querySelector('.custom-select-trigger');
    const options = select.querySelector('.custom-options');
    const hiddenInput = document.getElementById(select.dataset.name);

    trigger.addEventListener('click', () => {
        select.classList.toggle('open');
    });

    select.querySelectorAll('.custom-option').forEach(option => {
        option.addEventListener('click', () => {
            const value = option.dataset.value;
            const text = option.textContent;

            trigger.textContent = text;
            hiddenInput.value = value;
            select.classList.remove('open');
        });
    });
});

document.addEventListener('click', e => {
    document.querySelectorAll('.custom-select.open').forEach(openSelect => {
        if (!openSelect.contains(e.target)) openSelect.classList.remove('open');
    });
});