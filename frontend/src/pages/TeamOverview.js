import React, { useEffect, useState } from 'react';
import { reportAPI } from '../services/api';
import './TeamOverview.css';

function TeamOverview() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      setLoading(true);
      const response = await reportAPI.getUsers();
      setUsers(response.data || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div className="team-overview"><p>Loading...</p></div>;
  if (error) return <div className="team-overview"><p>Error: {error}</p></div>;

  return (
    <div className="team-overview">
      <h1>Team Overview</h1>
      <div className="team-grid">
        {users.map((user) => (
          <div key={user.id} className="team-card">
            <h3>{user.name}</h3>
            <p>{user.email}</p>
            <p className="status">{user.active ? 'Active' : 'Inactive'}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default TeamOverview;
