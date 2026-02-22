function S = loader_sitl_csv(trial_csv_path, state_def_yaml_path)
%LOADER_SITL_CSV Load a SITL trial exported by ubuntu scripts into MATLAB.
%
% Inputs:
%   trial_csv_path        - path to trial_for_matlab.csv
%   state_def_yaml_path   - path to config/state_definition.yaml
%
% Output struct S:
%   S.t        [N x 1] time (s)
%   S.x_raw    [N x nx] raw state vector x (per state_definition ordering)
%   S.x_qd     [N x nx] quantized/decoded x if columns exist, else []
%   S.u        [N x nu] input proxy from inputs.csv merged into trial file, else []
%   S.meta     struct with mapping + column availability

    arguments
        trial_csv_path (1,:) char
        state_def_yaml_path (1,:) char
    end

    T = readtable(trial_csv_path);

    % Read YAML (MATLAB has readstruct for YAML in newer versions; fallback is simple parsing if needed)
    try
        cfg = readstruct(state_def_yaml_path, "FileType", "yaml");
    catch
        error("MATLAB cannot read YAML on this version. Use MATLAB R2021b+ or replace with a JSON contract.");
    end

    time_col = string(cfg.timebase.state_time_column);
    if ~ismember(time_col, string(T.Properties.VariableNames))
        error("Time column '%s' not found in trial CSV.", time_col);
    end

    t = T.(time_col);
    t = t(:);

    % Build x_raw using mapping_from_csv
    map = cfg.state_x.mapping_from_csv;
    order = string(cfg.state_x.ordering);
    nx = numel(order);
    x_raw = nan(height(T), nx);

    for i = 1:nx
        key = order(i);
        csv_col = string(map.(key));
        if ~ismember(csv_col, string(T.Properties.VariableNames))
            error("Required state column '%s' (for key '%s') not found in CSV.", csv_col, key);
        end
        x_raw(:, i) = T.(csv_col);
    end

    % Normalize quaternion if requested
    if isfield(cfg.attitude_conventions, "quaternion") && isfield(cfg.attitude_conventions.quaternion, "normalization")
        if cfg.attitude_conventions.quaternion.normalization
            % indices for quat in ordering
            qw = find(order=="quat_w");
            qx = find(order=="quat_x");
            qy = find(order=="quat_y");
            qz = find(order=="quat_z");
            if ~isempty(qw)
                qn = sqrt(x_raw(:,qw).^2 + x_raw(:,qx).^2 + x_raw(:,qy).^2 + x_raw(:,qz).^2);
                qn(qn==0) = 1;
                x_raw(:,qw) = x_raw(:,qw)./qn;
                x_raw(:,qx) = x_raw(:,qx)./qn;
                x_raw(:,qy) = x_raw(:,qy)./qn;
                x_raw(:,qz) = x_raw(:,qz)./qn;
            end
        end
    end

    % Build x_qd if quantized columns exist (suffix "_qd")
    suffix = "_qd";
    if isfield(cfg.quantization_contract, "quantized_suffix")
        suffix = string(cfg.quantization_contract.quantized_suffix);
    end

    x_qd = [];
    have_all_qd = true;
    for i = 1:nx
        key = order(i);
        csv_col = string(map.(key));
        qd_col = csv_col + suffix;
        if ~ismember(qd_col, string(T.Properties.VariableNames))
            have_all_qd = false;
            break
        end
    end

    if have_all_qd
        x_qd = nan(height(T), nx);
        for i = 1:nx
            key = order(i);
            csv_col = string(map.(key));
            qd_col = csv_col + suffix;
            x_qd(:, i) = T.(qd_col);
        end

        % Normalize quaternion for x_qd too
        qw = find(order=="quat_w");
        qx = find(order=="quat_x");
        qy = find(order=="quat_y");
        qz = find(order=="quat_z");
        if ~isempty(qw)
            qn = sqrt(x_qd(:,qw).^2 + x_qd(:,qx).^2 + x_qd(:,qy).^2 + x_qd(:,qz).^2);
            qn(qn==0) = 1;
            x_qd(:,qw) = x_qd(:,qw)./qn;
            x_qd(:,qx) = x_qd(:,qx)./qn;
            x_qd(:,qy) = x_qd(:,qy)./qn;
            x_qd(:,qz) = x_qd(:,qz)./qn;
        end
    end

    % Build u (input proxy) from columns present in trial CSV
    % We search for known column sets produced by 03_log_inputs_from_ulog.py
    u = [];
    if all(ismember(["T_proxy","tau_x","tau_y","tau_z"], string(T.Properties.VariableNames)))
        u = [T.T_proxy, T.tau_x, T.tau_y, T.tau_z];
        u_names = ["T_proxy","tau_x","tau_y","tau_z"];
    elseif all(ismember(["T_proxy","p_sp","q_sp","r_sp"], string(T.Properties.VariableNames)))
        u = [T.T_proxy, T.p_sp, T.q_sp, T.r_sp];
        u_names = ["T_proxy","p_sp","q_sp","r_sp"];
    elseif all(ismember(["u0","u1","u2","u3"], string(T.Properties.VariableNames)))
        u = [T.u0, T.u1, T.u2, T.u3];
        u_names = ["u0","u1","u2","u3"];
    else
        u_names = string.empty;
    end

    S = struct();
    S.t = t;
    S.x_raw = x_raw;
    S.x_qd = x_qd;
    S.u = u;
    S.meta = struct();
    S.meta.state_ordering = order;
    S.meta.state_mapping = map;
    S.meta.time_column = time_col;
    S.meta.has_x_qd = ~isempty(x_qd);
    S.meta.u_names = u_names;
    S.meta.csv_columns = string(T.Properties.VariableNames);
end
