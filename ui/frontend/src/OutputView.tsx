import { type ReactNode } from 'react';
import {
  BriefcaseBusiness, CalendarDays, Code2, FileCheck2, HeartPulse,
  ListChecks, Mail, MapPinned, Scale, ShoppingBasket,
} from 'lucide-react';
import { structuredOutputSchema, type RunEvent, type StructuredOutput } from './api';

const technicalFields = new Set([
  'action_id', 'goal_id', 'decision_id', 'effect', 'evidence', 'evidence_refs', 'mutation',
  'tool_receipt_id', 'event_id', 'message_id', 'provider_id', 'execution_state',
  'executed_at', 'system', 'status', 'owner_id', 'objective', 'success_criteria',
  'constraints', 'campaign_id', 'source_event_id', 'summary', 'question', 'rationale',
  'dissent', 'unresolved', 'perspectives', 'unknowns',
]);

function isTechnicalField(name: string) {
  return technicalFields.has(name) || name.endsWith('_id') || name.endsWith('_ids');
}

function label(value: string) {
  if (value === 'recommendation_option') return 'Recommendation';
  return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

const publicTypeLabels: Record<string, string> = {
  calendar_review: 'Calendar',
  email_triage: 'Email',
  shopping_plan: 'Meal plan',
  software_project_delivery: 'Software project',
  verification_report: 'Verification',
  opportunity_set: 'Findings',
  decision_brief: 'Decision',
  artifact_receipt: 'Document',
  action_plan: 'Plan',
};

function typeLabel(value: string) {
  return publicTypeLabels[value] ?? label(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function family(output: StructuredOutput) {
  const keys = new Set(Object.keys(output.data));
  const type = output.output_type;
  if (keys.has('events') || type.includes('calendar')) return 'calendar';
  if (keys.has('messages') || type.includes('email')) return 'email';
  if (keys.has('dinners') || keys.has('shopping_items') || type.includes('shopping')) return 'shopping';
  if (keys.has('changed_files') || type.includes('software_project')) return 'software';
  if (keys.has('targets') || type.includes('verification')) return 'availability';
  if (keys.has('options') || type.includes('decision')) return 'decision';
  if (type.includes('health')) return 'health';
  if (type.includes('application') || type.includes('career')) return 'career';
  if (keys.has('mutation') || type.includes('artifact') || type.includes('document')) return 'document';
  return 'general';
}

const icons = {
  calendar: CalendarDays,
  email: Mail,
  shopping: ShoppingBasket,
  software: Code2,
  availability: MapPinned,
  decision: Scale,
  health: HeartPulse,
  career: BriefcaseBusiness,
  document: FileCheck2,
  general: ListChecks,
};

function scalar(value: unknown) {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (value === null || value === undefined || value === '') return 'Not provided';
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString(undefined, {
        weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      });
    }
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'bigint') {
    return String(value);
  }
  return JSON.stringify(value);
}

function RecordItem({ record }: { record: Record<string, unknown> }) {
  const entries = Object.entries(record).filter(([key]) => !isTechnicalField(key));
  const titleKey = ['title', 'name', 'subject', 'option'].find(key => typeof record[key] === 'string' && record[key]);
  return <>
    {titleKey && <h4>{String(record[titleKey])}</h4>}
    <dl>{entries
      .filter(([key]) => !(titleKey && ['title', 'name', 'subject', 'option'].includes(key) && record[key] === record[titleKey]))
      .map(([key, child]) => <Value key={key} name={key} value={child} />)}</dl>
  </>;
}

function Value({ name, value }: { name: string; value: unknown }): ReactNode {
  if (Array.isArray(value)) {
    const items: unknown[] = value;
    if (!items.length) return null;
    const primitives = items.every(item => !isRecord(item) && !Array.isArray(item));
    return <section className="output-section">
      <h3>{label(name)}</h3>
      {primitives
        ? <ul className="output-list">{items.map((item, index) => <li key={index}>{scalar(item)}</li>)}</ul>
        : <div className="output-items">{items.map((item, index) => <article className="output-item" key={index}>
          {isRecord(item)
            ? <RecordItem record={item} />
            : scalar(item)}
        </article>)}</div>}
    </section>;
  }
  if (isRecord(value)) {
    return <section className="output-section output-object">
      <h3>{label(name)}</h3>
      <dl>{Object.entries(value).map(([key, child]) => <Value key={key} name={key} value={child} />)}</dl>
    </section>;
  }
  return <div className="output-field"><dt>{label(name)}</dt><dd>{scalar(value)}</dd></div>;
}

function day(value: unknown) {
  const match = typeof value === 'string' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  if (!match) return scalar(value);
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    .toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

function quantity(line: Record<string, unknown>) {
  const amount = Number(line.quantity);
  const shown = Number.isInteger(amount) ? String(amount) : amount.toFixed(1);
  return line.unit === 'each' ? `${shown} × ${String(line.item)}` : `${shown} ${String(line.unit)} ${String(line.item)}`;
}

const records = (value: unknown) => (Array.isArray(value) ? value.filter(isRecord) : []);
const texts = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []);

function HouseholdView({ output }: { output: StructuredOutput }) {
  const data = output.data;
  const prep = isRecord(data.prep) ? data.prep : null;
  const dinners = records(data.meal_plan);
  const restock = records(data.restock);
  const questions = texts(data.questions_for_person);
  const total = typeof data.restock_total_gbp === 'number' ? data.restock_total_gbp : null;
  const label = prep ? 'Dinner prep' : 'Dinners and shopping';
  return <article className="structured-output output-household" aria-label={`${label} output: ${output.title}`}>
    <header><span className="output-icon" aria-hidden="true"><ShoppingBasket size={19} /></span><div>
      {output.title !== label && <span>{label}</span>}<h2>{output.title}</h2>
    </div></header>
    <div className="output-body household">
      {prep && <>
        <p className="household-lede">Start at <strong>{String(prep.start_cooking_at)}</strong> to eat at {String(prep.eat_at)} · serves {String(prep.servings)}</p>
        {texts(prep.eating).length > 0 && <p className="household-note">For {texts(prep.eating).join(', ')}</p>}
        {records(prep.ingredients).length > 0 && <section className="output-section"><h3>Ingredients</h3>
          <ul className="output-list">{records(prep.ingredients).map((line, index) => <li key={index}>{quantity(line)}</li>)}</ul></section>}
        {texts(prep.steps).length > 0 && <section className="output-section"><h3>Method</h3>
          <ol className="output-list">{texts(prep.steps).map((step, index) => <li key={index}>{step}</li>)}</ol></section>}
      </>}
      {!prep && dinners.length > 0 && <section className="output-section"><h3>Dinners</h3>
        <ul className="household-rows">{dinners.map((dinner, index) => <li key={index}>
          <span className="household-day">{day(dinner.day)}</span>
          <span>{dinner.recipe ? scalar(dinner.recipe) : 'Dinner'}</span>
          <span className="household-meta">{String(dinner.servings)} · {String(dinner.eat_at)}</span>
        </li>)}</ul></section>}
      {restock.length > 0 && <section className="output-section"><h3>To buy</h3>
        <ul className="household-rows">{restock.map((line, index) => <li key={index}>
          <span className="household-day">{String(line.packs)} ×</span>
          <span>{String(line.name)}</span>
          <span className="household-meta">£{Number(line.cost_gbp).toFixed(2)}</span>
        </li>)}</ul>
        {total !== null && <p className="household-total">Total £{total.toFixed(2)}</p>}</section>}
      {questions.length > 0 && <section className="output-section"><h3>Needs your answer</h3>
        <ul className="output-list">{questions.map((question, index) => <li key={index}>{question}</li>)}</ul></section>}
    </div>
  </article>;
}

const targetStatus: Record<string, string> = {
  confirmed: 'Confirmed', likely: 'Likely', unavailable: 'Unavailable', unknown: 'Not confirmed',
};

function safeUrl(value: unknown) {
  if (typeof value !== 'string') return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed : null;
  } catch { return null; }
}

function VerificationView({ output }: { output: StructuredOutput }) {
  const targets = records(output.data.targets);
  const nextChecks = texts(output.data.next_checks);
  const confirmed = targets.filter(target => target.status === 'confirmed').length;
  return <article className="structured-output output-verification" aria-label={`Verification output: ${output.title}`}>
    <header><span className="output-icon" aria-hidden="true"><MapPinned size={19} /></span><div>
      <span>Verification</span><h2>{confirmed} of {targets.length} confirmed</h2>
    </div></header>
    <div className="output-body">
      <ul className="verification-rows">{targets.map((target, index) => {
        const url = safeUrl(target.url);
        const name = typeof target.name === 'string' && target.name ? target.name : scalar(target.source_name);
        const finding = typeof target.finding === 'string' && target.finding ? target.finding : scalar(target.description);
        return <li key={index}>
          <div className="verification-head"><strong>{name}</strong><span>{targetStatus[String(target.status)] ?? scalar(target.status)}</span></div>
          <p>{finding}</p>
          <p className="verification-meta">
            {typeof target.location === 'string' && target.location && <span>{target.location}</span>}
            {url && <a href={url.href} target="_blank" rel="noreferrer noopener">{url.hostname.replace(/^www\./, '')} ↗</a>}
          </p>
        </li>;
      })}</ul>
      {nextChecks.length > 0 && <section className="output-section"><h3>Still to check</h3>
        <ul className="output-list">{nextChecks.map((check, index) => <li key={index}>{check}</li>)}</ul></section>}
    </div>
  </article>;
}

export function OutputView({ event }: { event: RunEvent }) {
  const output = structuredOutputSchema.parse(event.data);
  if (output.output_type === 'meal_prep' || output.output_type === 'household_plan') {
    return <HouseholdView output={output} />;
  }
  if (output.output_type === 'verification_report' && records(output.data.targets).length) {
    return <VerificationView output={output} />;
  }
  const outputFamily = family(output);
  const Icon = icons[outputFamily];
  const entries = Object.entries(output.data);
  const primary = entries.filter(([key]) => (
    !isTechnicalField(key)
    && (outputFamily !== 'decision' || key === 'recommendation_option')
  ));
  if (!primary.length) return null;
  const safeType = output.output_type.replace(/[^a-z0-9_-]/g, '-');
  const outputLabel = typeLabel(output.output_type);
  const displayTitle = output.title.length <= 120 ? output.title : outputLabel;
  return <article className={`structured-output output-${safeType} output-family-${outputFamily}`} aria-label={`${outputLabel} output: ${displayTitle}`}>
    <header><span className="output-icon" aria-hidden="true"><Icon size={19} /></span><div>
      {displayTitle !== outputLabel && <span>{outputLabel}</span>}<h2>{displayTitle}</h2>
    </div></header>
    <div className="output-body">{primary.map(([key, value]) => <Value key={key} name={key} value={value} />)}</div>
  </article>;
}