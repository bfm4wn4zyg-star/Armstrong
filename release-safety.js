(function (root) {
  'use strict';
  var statuses = new Set(['未开始','进行中','已完成','不适用','已延误','阻塞','待确认','待签署','暂停','待图档','待排期','待处理','待归档','资料准备中','开模中','制作中']);
  function validationError(message) {
    var parts = message.split(' / ');
    return new Error(parts.length > 1 ? parts[root.DASHBOARD_LANG === 'en' ? 0 : 1] : message);
  }
  function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
  function text(value) { return typeof value === 'string'; }
  function list(value, valid) { return Array.isArray(value) && value.every(valid); }
  function unique(rows, key) {
    var values = rows.map(function (row) { return row[key].trim().toLowerCase(); });
    return values.every(Boolean) && new Set(values).size === values.length;
  }
  function validDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var date = new Date(value + 'T00:00:00Z');
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }
  function milestone(row) { return object(row) && text(row.id) && text(row.name) && text(row.phase); }
  function variant(row) {
    return object(row) && text(row.name) && text(row.node) && text(row.status) &&
      (row.milestones === undefined || list(row.milestones, milestone));
  }
  function project(row) {
    return object(row) && ['id','name','part','owner','priority'].every(function (key) { return text(row[key]); }) &&
      list(row.variants, variant) && unique(row.variants, 'name') &&
      list(row.milestones, milestone) && unique(row.milestones, 'id') &&
      list(row.approvals, object) && list(row.samples, Array.isArray);
  }
  function sample(row) {
    return object(row) && ['id','family','sample','qty','fabric','drawing','production','due','status','owner','remarks'].every(function (key) { return text(row[key]); });
  }
  function validateBucket(kind, bucket) {
    if (!object(bucket) || !Number.isInteger(bucket.revision) || bucket.revision < 0 ||
        !list(bucket.records, kind === 'series' ? project : sample) || !unique(bucket.records, 'id')) {
      throw validationError('Invalid shared data: ' + kind);
    }
    return bucket.records;
  }
  function validateBootstrap(data) {
    if (!object(data) || !['viewer','pm','admin'].includes(data.role) || !text(data.name) || !text(data.csrf) || !object(data.state)) {
      throw validationError('Invalid workspace bootstrap');
    }
    validateBucket('series', data.state.series);
    validateBucket('samples', data.state.samples);
    return data;
  }
  function prepareRecords(kind, records, previous, role) {
    var copy = JSON.parse(JSON.stringify(records));
    if (kind !== 'series' || role !== 'pm') return copy;
    var originals = new Map(previous.map(function (row) { return [row.id, row]; }));
    if (copy.length !== previous.length) throw validationError('PM cannot add or delete product series.');
    return copy.map(function (row) {
      var original = originals.get(row.id);
      if (!original) throw validationError('PM cannot create a product series.');
      return Object.assign({}, original, {variants:row.variants, approvals:row.approvals, updated:row.updated});
    });
  }
  function validateChanges(kind, records, previous) {
    var oldProjects = new Map(previous.map(function (row) { return [row.id, row]; }));
    function checkText(row, keys) {
      keys.forEach(function (key) {
        if (row[key] !== undefined && (!text(row[key]) || row[key].length > 20000)) throw validationError('Invalid text: ' + key);
      });
    }
    function checkRow(row, old, label) {
      if (!statuses.has(row.status)) throw validationError(label + ': invalid status / 状态无效');
      ['due','actual','updated'].forEach(function (key) {
        if (row[key] && (!old || old[key] !== row[key]) && !validDate(row[key])) throw validationError(label + ': invalid date / 日期无效');
      });
      if (row.status === '已完成' && (!old || old.status !== '已完成') && !validDate(row.actual || '')) {
        throw validationError(label + ': enter actual completion date / 请填写实际完成日期');
      }
    }
    records.forEach(function (row) {
      var old = oldProjects.get(row.id);
      checkText(row, Object.keys(row).filter(function (key) { return typeof row[key] === 'string'; }));
      if (kind === 'samples') {
        if (!row.family.trim() || !row.sample.trim()) throw validationError('Enter sample name / 请填写样品名称');
        if (!statuses.has(row.status)) throw validationError('Invalid sample status / 样品状态无效');
        if (row.due && (!old || old.due !== row.due) && !validDate(row.due)) throw validationError('Invalid due date / 承诺日期无效');
        var progress = Number(row.progress === undefined ? 0 : row.progress);
        if (!Number.isFinite(progress) || progress < 0 || progress > 100) throw validationError('Progress must be 0–100 / 进度必须为0–100');
        return;
      }
      if (!row.name.trim() || row.name.length > 200) throw validationError('Invalid series name / 产品系列名称应为1–200字');
      if (row.releaseDate && (!old || row.releaseDate !== old.releaseDate) && !validDate(row.releaseDate)) throw validationError('Invalid release date / 发布日期无效');
      row.approvals.forEach(function (approval, index) {
        var prior = old && old.approvals[index];
        if (!statuses.has(approval.status)) throw validationError('Invalid confirmation status / 确认状态无效');
        ['submitted','needed','confirmedOn'].forEach(function (key) {
          if (approval[key] && (!prior || approval[key] !== prior[key]) && !validDate(approval[key])) throw validationError('Invalid confirmation date / 确认事项日期无效');
        });
      });
      var groups = [{next:row.milestones, previous:old ? old.milestones : []}];
      row.variants.forEach(function (variant, index) {
        var before = old && (old.variants.find(function (item) { return item.name === variant.name; }) || old.variants[index]);
        if (!variant.name.trim() || variant.name.length > 200) throw validationError('Invalid model name / 型号名称应为1–200字');
        checkText(variant, ['name','node','r','a','approval','next']);
        groups.push({next:variant.milestones, previous:before ? before.milestones || [] : []});
      });
      groups.forEach(function (group) {
        var originals = new Map(group.previous.map(function (item) { return [item.id, item]; }));
        group.next.forEach(function (item) {
          checkText(item, ['name','r','a','next']);
          checkRow(item, originals.get(item.id), row.name + ' · ' + item.name);
        });
      });
    });
    return records;
  }
  var api = {validateBootstrap:validateBootstrap, validateBucket:validateBucket, prepareRecords:prepareRecords, validateChanges:validateChanges, validDate:validDate};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ArmstrongSafety = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
