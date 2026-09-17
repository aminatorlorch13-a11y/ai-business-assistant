function csrf(){
    return document.cookie.split('; ')
        .find(x=>x.startsWith('assistant_csrf='))
        ?.split('=')[1] || '';
}

async function api(url,options={}){
    const headers={
        'Content-Type':'application/json',
        'X-CSRF-Token':csrf(),
        ...(options.headers||{})
    };

    const r=await fetch(url,{
        credentials:'same-origin',
        ...options,
        headers
    });

    const data=await r.json().catch(()=>({}));

    if(!r.ok){
        throw new Error(data.error||'Request failed.');
    }

    return data;
}

function wireAuthForm(id,url){
    document.getElementById(id).addEventListener('submit',async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const error=document.getElementById('error');
        error.textContent='';

        try{
            await api(url,{
                method:'POST',
                body:JSON.stringify(Object.fromEntries(f))
            });

            location.href='/dashboard';
        }catch(x){
            error.textContent=x.message;
        }
    });
}

function wireSignupForm(){
    document.getElementById('signup').addEventListener('submit',async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const error=document.getElementById('error');
        error.textContent='';

        try{
            await api('/api/auth/signup',{
                method:'POST',
                body:JSON.stringify(Object.fromEntries(f))
            });

            location.href='/login';
        }catch(x){
            error.textContent=x.message;
        }
    });
}

function addMessage(who,text){
    const box=document.getElementById('messages');
    const div=document.createElement('div');

    div.className='message '+who;
    div.textContent=text;

    box.appendChild(div);
    box.scrollTop=box.scrollHeight;
}

function wireDashboard(){
    document.getElementById('logout').onclick=async()=>{
        try{
            await api('/api/auth/logout',{method:'POST'});
        }finally{
            location.href='/login';
        }
    };

    document.getElementById('assistant-form').onsubmit=async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const text=f.get('message');
        const err=document.getElementById('assistant-error');

        err.textContent='';
        addMessage('user',text);
        e.target.reset();

        try{
            const data=await api('/api/assistant/message',{
                method:'POST',
                body:JSON.stringify({message:text})
            });

            addMessage('assistant',data.message);
        }catch(x){
            err.textContent=x.message;
        }
    };

    document.getElementById('config-form').onsubmit=async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const msg=document.getElementById('config-message');

        try{
            await api('/api/business/config',{
                method:'POST',
                body:JSON.stringify(Object.fromEntries(f))
            });

            msg.textContent='Saved.';
        }catch(x){
            msg.textContent=x.message;
        }
    };
}

function founderValue(value){
    return value===null ||
           value===undefined ||
           value===''
        ? '—'
        : String(value);
}

function founderField(label,value){
    const div=document.createElement('div');
    div.className='founder-field';

    const strong=document.createElement('strong');
    strong.textContent=label;

    const text=document.createElement('span');
    text.textContent=founderValue(value);

    div.appendChild(strong);
    div.appendChild(text);

    return div;
}

function renderFounderBusinesses(items){
    const box=document.getElementById('businesses');
    box.textContent='';

    if(!items.length){
        const empty=document.createElement('p');
        empty.className='muted';
        empty.textContent='No businesses found.';
        box.appendChild(empty);
        return;
    }

    for(const item of items){
        const article=document.createElement('article');
        article.className='founder-business';

        const title=document.createElement('h3');
        title.textContent=founderValue(item.name);
        article.appendChild(title);

        const grid=document.createElement('div');
        grid.className='founder-business-grid';

        grid.appendChild(
            founderField('Business ID',item.business_id)
        );

        grid.appendChild(
            founderField('Users',item.user_count)
        );

        grid.appendChild(
            founderField(
                'Owner',
                item.owner
                    ? `${founderValue(item.owner.display_name)} (${founderValue(item.owner.email)})`
                    : 'No owner membership'
            )
        );

        grid.appendChild(
            founderField('Owner User ID',item.owner?.user_id)
        );

        grid.appendChild(
            founderField('Assistant',item.assistant?.name)
        );

        grid.appendChild(
            founderField('Voice',item.assistant?.voice)
        );

        grid.appendChild(
            founderField('Commercial Status',item.commercial?.status)
        );

        grid.appendChild(
            founderField(
                'Execution Allowed',
                item.commercial?.execution_allowed
            )
        );

        grid.appendChild(
            founderField(
                'Execution Reason',
                item.commercial?.execution_reason
            )
        );

        grid.appendChild(
            founderField(
                'Trial Started',
                item.commercial?.trial_started_at
            )
        );

        grid.appendChild(
            founderField(
                'Trial Ends',
                item.commercial?.trial_ends_at
            )
        );

        grid.appendChild(
            founderField(
                'Paid Evidence',
                item.commercial?.paid
            )
        );

        grid.appendChild(
            founderField(
                'Purchase Count',
                item.commercial?.purchase_count
            )
        );

        grid.appendChild(
            founderField(
                'Last Event',
                item.operational?.last_event_at
            )
        );

        article.appendChild(grid);

        if(item.commercial?.last_purchase){
            const purchase=item.commercial.last_purchase;
            const purchaseBox=document.createElement('div');

            purchaseBox.className='founder-field';
            purchaseBox.style.marginTop='12px';

            purchaseBox.appendChild(
                founderField(
                    'Payment Provider',
                    purchase.provider
                )
            );

            purchaseBox.appendChild(
                founderField(
                    'Payment Amount',
                    purchase.amount
                )
            );

            purchaseBox.appendChild(
                founderField(
                    'Payment Currency',
                    purchase.currency
                )
            );

            purchaseBox.appendChild(
                founderField(
                    'Paid At',
                    purchase.paid_at
                )
            );

            article.appendChild(purchaseBox);
        }

        box.appendChild(article);
    }
}

function renderFounderEvents(items){
    const box=document.getElementById('events');
    box.textContent='';

    if(!items.length){
        const empty=document.createElement('p');
        empty.className='muted';
        empty.textContent='No platform events recorded.';
        box.appendChild(empty);
        return;
    }

    for(const item of items){
        const article=document.createElement('article');
        article.className='founder-event';

        const heading=document.createElement('strong');

        heading.textContent=
            `${founderValue(item.event_type)} · `+
            `${founderValue(item.outcome)}`;

        const details=document.createElement('p');
        details.className='muted';

        details.textContent=
            `${founderValue(item.occurred_at)} · `+
            `${founderValue(item.channel)} · `+
            `${founderValue(item.action)}`;

        const evidence=document.createElement('code');
        evidence.textContent=JSON.stringify(item,null,2);

        article.appendChild(heading);
        article.appendChild(details);
        article.appendChild(evidence);

        box.appendChild(article);
    }
}

function setFounderMetric(key,metric){
    const value=document.getElementById(`metric-${key}`);
    const status=document.getElementById(`metric-${key}-status`);

    if(!value || !status){
        return;
    }

    value.textContent=founderValue(metric?.value);

    status.textContent=
        metric?.status === 'available'
            ? 'AUTHORITATIVE'
            : founderValue(metric?.status).toUpperCase();
}

function setFounderInstrumentationMetric(key,metric){
    const value=document.getElementById(`metric-${key}`);
    const status=document.getElementById(`metric-${key}-status`);

    if(!value || !status){
        return;
    }

    value.textContent=founderValue(metric?.value);
    status.textContent=founderValue(metric?.status).toUpperCase();
}

function setFounderText(id,value){
    const element=document.getElementById(id);

    if(element){
        element.textContent=founderValue(value);
    }
}

function renderFounderChannels(channels){
    const box=document.getElementById('channel-events');

    if(!box){
        return;
    }

    box.textContent='';

    const entries=Object.entries(channels||{});

    if(!entries.length){
        const empty=document.createElement('p');
        empty.className='muted';
        empty.textContent='No channel telemetry recorded.';
        box.appendChild(empty);
        return;
    }

    for(const [channel,count] of entries){
        const cell=document.createElement('div');
        cell.className='channel-cell';

        const label=document.createElement('span');
        label.textContent=channel;

        const value=document.createElement('strong');
        value.textContent=founderValue(count);

        cell.appendChild(label);
        cell.appendChild(value);

        box.appendChild(cell);
    }
}

function renderFounderAnalytics(data){
    setFounderMetric('businesses',data.businesses);
    setFounderMetric('active',data.active_businesses);
    setFounderMetric('trials',data.trial_businesses);
    setFounderMetric('conversions',data.trial_conversions);
    setFounderMetric('conversion-rate',data.trial_conversion_rate);
    setFounderMetric('revenue',data.revenue);
    setFounderMetric('execution-volume',data.execution_volume);
    setFounderMetric('events',data.recorded_events);

    setFounderText('state-trial',data.trial_businesses?.value);
    setFounderText('state-active',data.active_businesses?.value);
    setFounderText('state-expired',data.expired_businesses?.value);
    setFounderText('state-suspended',data.suspended_businesses?.value);

    setFounderText('events-success',data.successful_events?.value);
    setFounderText('events-failure',data.failed_events?.value);
    setFounderText('events-denied',data.denied_events?.value);
    setFounderText('events-error-count',data.error_events?.value);

    setFounderInstrumentationMetric(
        'integration-health',
        data.integration_health
    );

    setFounderInstrumentationMetric(
        'website-visitors',
        data.website_visitors
    );

    setFounderInstrumentationMetric(
        'website-page-views',
        data.website_page_views
    );

    setFounderInstrumentationMetric(
        'purchases',
        data.verified_purchases
    );

    renderFounderChannels(data.channel_events);
}

async function loadFounderAnalytics(){
    const banner=document.querySelector('.telemetry-label');

    try{
        const data=await api('/api/founder/analytics');

        renderFounderAnalytics(data);

        if(banner){
            banner.textContent='LIVE DATA';
        }
    }catch(x){
        if(banner){
            banner.textContent='TELEMETRY ERROR';
        }

        const metricIds=[
            'metric-businesses',
            'metric-active',
            'metric-trials',
            'metric-conversions',
            'metric-conversion-rate',
            'metric-revenue',
            'metric-execution-volume',
            'metric-events'
        ];

        for(const id of metricIds){
            const element=document.getElementById(id);

            if(element){
                element.textContent='ERROR';
            }
        }
    }
}

async function loadFounderBusinesses(){
    const error=document.getElementById('founder-error');
    error.textContent='';

    try{
        const data=await api('/api/founder/businesses');
        renderFounderBusinesses(data.businesses||[]);
    }catch(x){
        error.textContent=x.message;
    }
}

async function loadFounderEvents(){
    const error=document.getElementById('events-error');
    error.textContent='';

    try{
        const data=await api('/api/founder/events');
        renderFounderEvents(data.events||[]);
    }catch(x){
        error.textContent=x.message;
    }
}

function wireFounderDashboard(){
    document.getElementById('founder-logout').onclick=async()=>{
        try{
            await api('/api/auth/logout',{method:'POST'});
        }finally{
            location.href='/login';
        }
    };

    document.getElementById('refresh-businesses').onclick=
        loadFounderBusinesses;

    document.getElementById('refresh-events').onclick=
        loadFounderEvents;

    loadFounderAnalytics();
    loadFounderBusinesses();
    loadFounderEvents();
}
